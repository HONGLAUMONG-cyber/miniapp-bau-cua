import os
import json
import asyncio
import time
import random
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Ép hệ thống dùng múi giờ Việt Nam
os.environ['TZ'] = 'Asia/Ho_Chi_Minh'
try:
    time.tzset()
except AttributeError:
    pass

# --- CẤU HÌNH ---
TOKEN = '8590503487:AAHgMPAbg7TYEFMy7SbeTyIZeiPfVXzQYOs' 
ADMIN_ID = 7113504762  
GROUP_WITHDRAW_ID = -1003950088167 
DB_FILE = 'users_db.json'

# Thông tin ngân hàng
MY_STK = '086304890'
MY_BANK = 'VIB'
MY_NAME = 'PHUNG VAN MAU'

REFERRAL_REWARD = 500 
MIN_WITHDRAW = 20000 

# --- HỆ THỐNG HOA HỒNG 7 TẦNG (TRÊN THU NHẬP) ---
REF_PERCENTAGES = [0.40, 0.35, 0.30, 0.25, 0.20, 0.10, 0.05]

REQUIRED_CHANNELS = [
    {"name": "📺 Trạm Giải Trí", "id": -1003971329928, "url": "https://t.me/tramgiaitri"},
    {"name": "🇻🇳 Trạm GenZ - TikTok", "id": -1002928339826, "url": "https://t.me/+CAp7MGZegRgwNDA1"},
    {"name": "🤖 Cỗ Máy In Tiền", "id": -1003941341991, "url": "https://t.me/HomeComayintien"},
    {"name": "📊 Hoá Đơn Thanh Toán", "id": -1003950088167, "url": "https://t.me/Thanhtoancomayintien"},
    {"name": "🎲 GR_Co_Xu", "id": -1002900522909, "url": "https://t.me/GR_Co_Xu"}
]

INVEST_PACKS = [
    {"min": 20000, "interest": 0.05, "days": 30, "icon": "🥉"},
    {"min": 50000, "interest": 0.06, "days": 40, "icon": "🥈"},
    {"min": 100000, "interest": 0.065, "days": 50, "icon": "🥇"},
    {"min": 200000, "interest": 0.066, "days": 60, "icon": "💎"},
    {"min": 500000, "interest": 0.068, "days": 60, "icon": "🔥"},
    {"min": 1000000, "interest": 0.07, "days": 100, "icon": "👑"}
]

# MAP ĐỔI XÚC XẮC SANG LINH VẤT BẦU CUA
BOU_CUA_MAP = {
    1: {"name": "bầu", "emoji": "🎃"},
    2: {"name": "cua", "emoji": "🦀"},
    3: {"name": "tôm", "emoji": "🦐"},
    4: {"name": "cá", "emoji": "🐟"},
    5: {"name": "gà", "emoji": "🐔"},
    6: {"name": "hươu", "emoji": "🦌"}
}

# --- QUẢN LÝ DỮ LIỆU ---
def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_data(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def log_transaction(user_data, amount, reason):
    user_data.setdefault("transactions", [])
    user_data["transactions"].append({
        "time": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "amount": amount,
        "reason": reason,
        "balance": user_data.get("balance", 0),
        "locked_balance": user_data.get("locked_balance", 0)
    })
    if len(user_data["transactions"]) > 50:
        user_data["transactions"] = user_data["transactions"][-50:]

# Hàm cập nhật số liệu Bảng xếp hạng Tuần/Tháng
def update_stats(u, stat_type, amount):
    now = datetime.now()
    week = now.strftime("%Y-%V")
    month = now.strftime("%Y-%m")
    if "stats" not in u: u["stats"] = {}
    
    # Kiểm tra reset Tuần
    if u["stats"].get("current_week") != week:
        u["stats"]["current_week"] = week
        u["stats"]["week_deposit"] = 0
        u["stats"]["week_invest"] = 0
        u["stats"]["week_bet"] = 0
        u["stats"]["week_ref"] = 0
    
    # Kiểm tra reset Tháng
    if u["stats"].get("current_month") != month:
        u["stats"]["current_month"] = month
        u["stats"]["month_deposit"] = 0
        u["stats"]["month_invest"] = 0
        u["stats"]["month_bet"] = 0
        u["stats"]["month_ref"] = 0
    
    if stat_type == "deposit":
        u["stats"]["week_deposit"] += amount
        u["stats"]["month_deposit"] += amount
    elif stat_type == "invest":
        u["stats"]["week_invest"] += amount
        u["stats"]["month_invest"] += amount
    elif stat_type == "bet":
        u["stats"]["week_bet"] += amount
        u["stats"]["month_bet"] += amount
    elif stat_type == "ref":
        u["stats"]["week_ref"] += amount
        u["stats"]["month_ref"] += amount

# --- HÀM CHI TRẢ HOA HỒNG TẦNG ---
async def pay_referral_commission(context, data, child_id, amount_earned, reason):
    current_child = child_id
    for i, percentage in enumerate(REF_PERCENTAGES):
        parent_id = data.get(str(current_child), {}).get("referrer")
        if not parent_id or str(parent_id) not in data:
            break
        commission = int(amount_earned * percentage)
        if commission > 0:
            data[str(parent_id)]["balance"] += commission
            log_transaction(data[str(parent_id)], commission, f"Hoa hồng F{i+1} ({reason})")
            try:
                await context.bot.send_message(
                    chat_id=int(parent_id),
                    text=f"🎁 *HOA HỒNG THU NHẬP (F{i+1})*\nBạn nhận được +{commission:,}đ ({int(percentage*100)}%) từ thu nhập {reason} của cấp dưới!",
                    parse_mode="Markdown"
                )
            except: pass
        current_child = parent_id

# --- TRẢ LÃI TỰ ĐỘNG ---
async def daily_interest_job(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    now = datetime.now()
    changed = False
    for user_id, u in data.items():
        if "investments" in u:
            active_investments = []
            for inv in u["investments"]:
                if inv["status"] == "active":
                    start_date = datetime.strptime(inv["start_date"], "%Y-%m-%d %H:%M:%S")
                    days_passed = (now - start_date).days
                    if days_passed >= 10:
                        has_reinvested = any(
                            new_inv["amount"] >= inv["amount"] and 
                            datetime.strptime(new_inv["start_date"], "%Y-%m-%d %H:%M:%S") > (start_date + timedelta(days=10))
                            for new_inv in u["investments"]
                        )
                        if not has_reinvested:
                            if days_passed >= 15:
                                try: await context.bot.send_message(chat_id=int(user_id), text=f"⚠️ *THÔNG BÁO HỦY GÓI*\nGói {inv['amount']:,}đ đã bị hủy do không tái đầu tư.", parse_mode="Markdown")
                                except: pass
                                changed = True
                                continue
                            if days_passed == 10 and not inv.get("notified_task"):
                                try: await context.bot.send_message(chat_id=int(user_id), text=f"📜 *NHIỆM VỤ:* Tái đầu tư gói ≥ {inv['amount']:,}đ để tiếp tục nhận lãi.", parse_mode="Markdown")
                                except: pass
                                inv["notified_task"] = True
                                changed = True
                            active_investments.append(inv)
                            continue
                    last_pay_str = inv["last_payment"]
                    if len(last_pay_str) <= 10: last_pay_str += " 00:00:00"
                    try: last_pay = datetime.strptime(last_pay_str, "%Y-%m-%d %H:%M:%S")
                    except: continue
                    if now >= last_pay + timedelta(hours=24):
                        profit = int(inv["amount"] * inv["interest"])
                        u["balance"] += profit
                        inv["last_payment"] = now.strftime("%Y-%m-%d %H:%M:%S")
                        inv["days_left"] -= 1
                        changed = True
                        log_transaction(u, profit, f"Lãi gói đầu tư {inv['amount']:,}đ")
                        try: await context.bot.send_message(chat_id=int(user_id), text=f"💰 *LÃI VỀ TÀI KHOẢN*\nGói {inv['amount']:,}đ: +{profit:,}đ", parse_mode="Markdown")
                        except: pass
                        await pay_referral_commission(context, data, user_id, profit, "đầu tư")
                active_investments.append(inv)
            u["investments"] = active_investments
    if changed: save_data(data)

# --- GIAO DIỆN ---
def main_menu(user_id):
    keyboard = [
        ['🏛 HỆ SINH THÁI', '🚀 KIẾM LỢI NHUẬN'], 
        ['👤 TRANG CÁ NHÂN', '💳 VÍ CỦA TÔI'], 
        ['🎲 TRÒ CHƠI', '🏦 NẠP TIỀN'], 
        ['🏦 RÚT VỀ NGÂN HÀNG', '📊 THỐNG KÊ'], 
        ['🏆 ĐUA TOP BXH', '📅 ĐIỂM DANH'],
        ['🆘 TRỢ GIÚP']
    ]
    if int(user_id) == ADMIN_ID: 
        keyboard.append(['⚙️ QUẢN TRỊ: CỘNG TIỀN', '📉 THU HỒI SỐ DƯ'])
        keyboard.append(['📢 PHÁT THÔNG BÁO', '🔍 CHECK BUFF REF'])
        keyboard.append(['📜 NHẬT KÝ REF', '🧾 LỊCH SỬ GIAO DỊCH'])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    user_id = str(user.id)
    if user_id not in data:
        referrer = context.args[0] if context.args else None
        data[user_id] = {
            "username": user.username or user.first_name, 
            "first_name": user.first_name,
            "balance": 0, 
            "locked_balance": 0, 
            "total_ref": 0, 
            "joined": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), 
            "investments": [], 
            "referrer": referrer, 
            "bet": 0, 
            "total_deposit": 0, 
            "ref_reward_paid": False,
            "transactions": [],
            "stats": {}
        }
        save_data(data)
        
    if not await is_subscribed(context, user.id):
        await update.message.reply_text("🏛 *BẢO CHỨNG HỆ THỐNG*\nĐể kích hoạt tài khoản và bắt đầu nhận lãi, vui lòng gia nhập toàn bộ kênh đối tác chiến lược bên dưới.", reply_markup=force_join_keyboard(), parse_mode="Markdown")
        return
        
    welcome_msg = (
        f"🌟 *KÍNH CHÀO ĐỐI TÁC: {user.first_name.upper()}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏦 *Chào mừng bạn đến với Cỗ Máy In Tiền v3.0*\n"
        "Hệ thống vận hành tài chính phi tập trung tự động hàng đầu trên Telegram.\n\n"
        "⚡️ *CƠ CHẾ VẬN HÀNH ĐỘC QUYỀN:*\n"
        "▪️ **Lợi nhuận thụ động:** Trả thẳng vào ví lên tới `7%/ngày`.\n"
        "▪️ **Đế chế Affiliate:** Chia sẻ hoa hồng 7 tầng trên tổng thu nhập.\n"
        "▪️ **Bảo mật tuyệt đối:** Thanh khoản chớp nhoáng, dòng tiền minh bạch.\n\n"
        "👇 *Hệ thống đã được kích hoạt. Hãy thao tác trên thanh Menu bên dưới để bắt đầu chuỗi ngày bùng nổ lợi nhuận!* 💸"
    )
    await update.message.reply_text(welcome_msg, reply_markup=main_menu(user.id), parse_mode="Markdown")

# --- LỆNH QUẢN TRỊ: NHẮN TIN CHO KHÁCH ---
async def admin_send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if int(user_id) != ADMIN_ID: 
        return
    
    text = update.message.text
    try:
        parts = text.split(" ", 2)
        if len(parts) >= 3:
            target_id = parts[1]
            msg_content = parts[2]
            await context.bot.send_message(
                chat_id=int(target_id), 
                text=f"📩 *THÔNG BÁO TỪ HỆ THỐNG:*\n\n{msg_content}", 
                parse_mode="Markdown"
            )
            await update.message.reply_text(f"✅ Đã gửi tin nhắn đến ID `{target_id}`", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Sai cú pháp. Dùng: `/send ID_KHÁCH Nội_dung_tin_nhắn`\nVí dụ: `/send 123456 Tài khoản bị khóa.`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: Không thể gửi (Khách đã chặn bot hoặc ID không hợp lệ).")

# ==========================================================
# --- MENU TRÒ CHƠI CHUYÊN NGHIỆP ---
# ==========================================================

def game_main_menu():
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 CHẴN LẺ | TÀI XỈU", callback_data="open_game_dice")],
        [InlineKeyboardButton("🎰 NỔ HŨ (SLOT MACHINE)", callback_data="open_game_slot")],
        [InlineKeyboardButton("🏀 BÓNG RỔ", callback_data="open_game_bb"), InlineKeyboardButton("⚽️ BÓNG ĐÁ", callback_data="open_game_fb")],
        [InlineKeyboardButton("🎯 PHI TIÊU", callback_data="open_game_dart")],
        [InlineKeyboardButton("🎃 BẦU CUA DÂN GIAN 🦀", callback_data="open_game_baucua")]
    ])
    text = "🎮 *TRUNG TÂM GIẢI TRÍ CAO CẤP*\n\nXin mời đối tác lựa chọn khu vực muốn tham gia:"
    return text, markup

# 0. MENU BẦU CUA
def game_menu_baucua(user_id, data):
    u = data.get(str(user_id), {})
    u.setdefault("locked_balance", 0)
    u.setdefault("bet", 0)
    u.setdefault("bc_doors", []) 
    
    doors = u.get("bc_doors", [])
    doors_text = ", ".join([BOU_CUA_MAP[int(d)]["name"].capitalize() for d in doors]) if doors else "Chưa chọn"
    
    def get_btn(d_val, d_emoji, d_name):
        return InlineKeyboardButton(f"{'[x] ' if str(d_val) in doors else ''}{d_emoji} {d_name}", callback_data=f"gs_bc_{d_val}")

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 1k", callback_data="g_1000"), InlineKeyboardButton("💵 5k", callback_data="g_5000"), InlineKeyboardButton("💵 10k", callback_data="g_10000")],
        [InlineKeyboardButton("💵 50k", callback_data="g_50000"), InlineKeyboardButton("💵 100k", callback_data="g_100000"), InlineKeyboardButton("💵 ALL", callback_data="g_all")],
        [get_btn(1, "🎃", "Bầu"), get_btn(2, "🦀", "Cua"), get_btn(3, "🦐", "Tôm")],
        [get_btn(4, "🐟", "Cá"), get_btn(5, "🐔", "Gà"), get_btn(6, "🦌", "Hươu")],
        [InlineKeyboardButton("✖️ XÓA CƯỢC/CỬA", callback_data="g_clear")],
        [InlineKeyboardButton("🎲 XÓC BẦU CUA 🎲", callback_data="gp_baucua")],
        [InlineKeyboardButton("🔙 QUAY LẠI", callback_data="open_game_main")]
    ])
    text = (f"🎃 **BẦU CUA DÂN GIAN** 🦀\n\n"
            f"🌟 *LUẬT CHƠI:*\n"
            f"Bạn có thể chọn NHIỀU CỬA. Bot sẽ tung 3 viên xúc xắc.\n"
            f"Thưởng **1 ăn 1.8** cho mỗi viên trúng cửa bạn chọn.\n\n"
            f"💰 Ví rút: `{u.get('balance', 0):,}đ`\n"
            f"🔒 Ví nạp: `{u.get('locked_balance', 0):,}đ`\n"
            f"👉 Đang cược (mỗi cửa): `{u.get('bet', 0):,}đ`\n"
            f"🎯 Cửa đã chọn: `{doors_text}`\n"
            f"💸 Tổng cược: `{u.get('bet', 0) * len(doors):,}đ`")
    return text, markup

# 1. MENU CHẴN LẺ TÀI XỈU
def game_menu_dice(user_id, data):
    u = data.get(str(user_id), {})
    u.setdefault("locked_balance", 0)
    u.setdefault("bet", 0)
    u.setdefault("side", None) 
    
    side_text = "Chưa chọn"
    if u.get('side') == 'chan': side_text = "🔴 CHẴN"
    elif u.get('side') == 'le': side_text = "🔵 LẺ"
    elif u.get('side') == 'tai': side_text = "📈 TÀI (4-6)"
    elif u.get('side') == 'xiu': side_text = "📉 XỈU (1-3)"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 1k", callback_data="g_1000"), InlineKeyboardButton("💵 5k", callback_data="g_5000"), InlineKeyboardButton("💵 10k", callback_data="g_10000")],
        [InlineKeyboardButton("💵 50k", callback_data="g_50000"), InlineKeyboardButton("💵 100k", callback_data="g_100000"), InlineKeyboardButton("💵 ALL", callback_data="g_all")],
        [InlineKeyboardButton("🔴 CHẴN", callback_data="gs_chan"), InlineKeyboardButton("✖️ XÓA CƯỢC", callback_data="g_clear"), InlineKeyboardButton("🔵 LẺ", callback_data="gs_le")],
        [InlineKeyboardButton("📈 TÀI", callback_data="gs_tai"), InlineKeyboardButton("➖", callback_data="ignore"), InlineKeyboardButton("📉 XỈU", callback_data="gs_xiu")],
        [InlineKeyboardButton("🎲 LẮC XÚC XẮC 🎲", callback_data="gp_roll")],
        [InlineKeyboardButton("🔙 QUAY LẠI MỤC TRÒ CHƠI", callback_data="open_game_main")]
    ])
    text = (f"🎲 **TRÒ CHƠI XÚC XẮC** 🎲\n"
            f"💰 Ví rút: `{u.get('balance', 0):,}đ`\n"
            f"🔒 Ví nạp: `{u.get('locked_balance', 0):,}đ`\n"
            f"👉 Đang cược: `{u.get('bet', 0):,}đ`\n"
            f"🎯 Cửa chọn: `{side_text}`")
    return text, markup

# 2. MENU NỔ HŨ
def game_menu_slot(user_id, data):
    u = data.get(str(user_id), {})
    u.setdefault("locked_balance", 0)
    u.setdefault("bet", 0)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 1k", callback_data="g_1000"), InlineKeyboardButton("💵 5k", callback_data="g_5000"), InlineKeyboardButton("💵 10k", callback_data="g_10000")],
        [InlineKeyboardButton("💵 50k", callback_data="g_50000"), InlineKeyboardButton("💵 100k", callback_data="g_100000"), InlineKeyboardButton("💵 ALL", callback_data="g_all")],
        [InlineKeyboardButton("✖️ XÓA CƯỢC", callback_data="g_clear")],
        [InlineKeyboardButton("🎰 QUAY HŨ NGAY 🎰", callback_data="gp_slot")],
        [InlineKeyboardButton("🔙 QUAY LẠI MỤC TRÒ CHƠI", callback_data="open_game_main")]
    ])
    text = (f"🎰 **NỔ HŨ LỘC PHÁT (SLOT MACHINE)** 🎰\n\n"
            f"🌟 *LUẬT CHƠI & GIẢI THƯỞNG:*\n"
            f"💥 **Nổ 7️⃣7️⃣7️⃣ (Jackpot):** Nhận ngay **x10** tiền cược.\n"
            f"🍒 **Nổ 3 hình giống nhau:** Nhận **x5** tiền cược.\n\n"
            f"💰 Ví rút: `{u.get('balance', 0):,}đ`\n"
            f"🔒 Ví nạp: `{u.get('locked_balance', 0):,}đ`\n"
            f"👉 Đang cược: `{u.get('bet', 0):,}đ`\n\n"
            f"💡 *Chỉ cần chọn mức cược và bấm QUAY HŨ!*")
    return text, markup

# 3. MENU BÓNG RỔ
def game_menu_bb(user_id, data):
    u = data.get(str(user_id), {})
    u.setdefault("locked_balance", 0)
    u.setdefault("bet", 0)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 1k", callback_data="g_1000"), InlineKeyboardButton("💵 5k", callback_data="g_5000"), InlineKeyboardButton("💵 10k", callback_data="g_10000")],
        [InlineKeyboardButton("💵 50k", callback_data="g_50000"), InlineKeyboardButton("💵 100k", callback_data="g_100000"), InlineKeyboardButton("💵 ALL", callback_data="g_all")],
        [InlineKeyboardButton("✖️ XÓA CƯỢC", callback_data="g_clear")],
        [InlineKeyboardButton("🏀 NÉM BÓNG NGAY 🏀", callback_data="gp_bb")],
        [InlineKeyboardButton("🔙 QUAY LẠI MỤC TRÒ CHƠI", callback_data="open_game_main")]
    ])
    text = (f"🏀 **BÓNG RỔ ĐỈNH CAO** 🏀\n\n"
            f"🌟 *LUẬT CHƠI:*\n"
            f"Nếu bóng vào rổ (Swish hoặc Đập bảng vào rổ), bạn nhận **1 ăn 2**.\n"
            f"Nếu ném trượt (Kẹt vành hoặc Bay ra ngoài), bạn mất tiền cược.\n\n"
            f"💰 Ví rút: `{u.get('balance', 0):,}đ`\n"
            f"🔒 Ví nạp: `{u.get('locked_balance', 0):,}đ`\n"
            f"👉 Đang cược: `{u.get('bet', 0):,}đ`")
    return text, markup

# 4. MENU BÓNG ĐÁ
def game_menu_fb(user_id, data):
    u = data.get(str(user_id), {})
    u.setdefault("locked_balance", 0)
    u.setdefault("bet", 0)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 1k", callback_data="g_1000"), InlineKeyboardButton("💵 5k", callback_data="g_5000"), InlineKeyboardButton("💵 10k", callback_data="g_10000")],
        [InlineKeyboardButton("💵 50k", callback_data="g_50000"), InlineKeyboardButton("💵 100k", callback_data="g_100000"), InlineKeyboardButton("💵 ALL", callback_data="g_all")],
        [InlineKeyboardButton("✖️ XÓA CƯỢC", callback_data="g_clear")],
        [InlineKeyboardButton("⚽️ SÚT PHẠT NGAY ⚽️", callback_data="gp_fb")],
        [InlineKeyboardButton("🔙 QUAY LẠI MỤC TRÒ CHƠI", callback_data="open_game_main")]
    ])
    text = (f"⚽️ **VUA PHÁ LƯỚI (PENALTY)** ⚽️\n\n"
            f"🌟 *LUẬT CHƠI:*\n"
            f"Sút tung lưới thủ môn nhận **1 ăn 1.5**.\n"
            f"Bị thủ môn bắt được hoặc sút ra ngoài, bạn mất tiền cược.\n\n"
            f"💰 Ví rút: `{u.get('balance', 0):,}đ`\n"
            f"🔒 Ví nạp: `{u.get('locked_balance', 0):,}đ`\n"
            f"👉 Đang cược: `{u.get('bet', 0):,}đ`")
    return text, markup

# 5. MENU PHI TIÊU
def game_menu_dart(user_id, data):
    u = data.get(str(user_id), {})
    u.setdefault("locked_balance", 0)
    u.setdefault("bet", 0)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 1k", callback_data="g_1000"), InlineKeyboardButton("💵 5k", callback_data="g_5000"), InlineKeyboardButton("💵 10k", callback_data="g_10000")],
        [InlineKeyboardButton("💵 50k", callback_data="g_50000"), InlineKeyboardButton("💵 100k", callback_data="g_100000"), InlineKeyboardButton("💵 ALL", callback_data="g_all")],
        [InlineKeyboardButton("✖️ XÓA CƯỢC", callback_data="g_clear")],
        [InlineKeyboardButton("🎯 PHÓNG TIÊU NGAY 🎯", callback_data="gp_dart")],
        [InlineKeyboardButton("🔙 QUAY LẠI MỤC TRÒ CHƠI", callback_data="open_game_main")]
    ])
    text = (f"🎯 **BULLSEYE PHI TIÊU** 🎯\n\n"
            f"🌟 *LUẬT CHƠI:*\n"
            f"Trúng chính giữa hồng tâm (Bullseye): Nhận **x3** tiền cược.\n"
            f"Trúng vòng thứ 2: Nhận **1 ăn 1.5**.\n"
            f"Các vòng ngoài hoặc trượt bảng: Mất tiền cược.\n\n"
            f"💰 Ví rút: `{u.get('balance', 0):,}đ`\n"
            f"🔒 Ví nạp: `{u.get('locked_balance', 0):,}đ`\n"
            f"👉 Đang cược: `{u.get('bet', 0):,}đ`")
    return text, markup

# ==========================================================

async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    data = load_data()
    
    text = update.message.text or update.message.caption or ""
    state = context.user_data.get('state')
    
    # --- SỬA LỖI MENU KHI ĐANG TRONG TRẠNG THÁI CHỜ ---
    MENU_COMMANDS = ['🏛 HỆ SINH THÁI', '🚀 KIẾM LỢI NHUẬN', '👤 TRANG CÁ NHÂN', '💳 VÍ CỦA TÔI', '🎲 TRÒ CHƠI', '🏦 NẠP TIỀN', '🏦 RÚT VỀ NGÂN HÀNG', '📊 THỐNG KÊ', '🆘 TRỢ GIÚP', '📢 PHÁT THÔNG BÁO', '⚙️ QUẢN TRỊ: CỘNG TIỀN', '📉 THU HỒI SỐ DƯ', '🔍 CHECK BUFF REF', '📜 NHẬT KÝ REF', '🧾 LỊCH SỬ GIAO DỊCH', '🏆 ĐUA TOP BXH', '📅 ĐIỂM DANH']
    if text in MENU_COMMANDS:
        context.user_data['state'] = None  
        state = None 

    if text == '🏛 HỆ SINH THÁI':
        msg = (
            "🏛 *ECOSYSTEM: CỖ MÁY IN TIỀN NETWORK*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🌐 *NỀN TẢNG TÀI CHÍNH PHI TẬP TRUNG*\n"
            "Chúng tôi xây dựng một tương lai nơi dòng tiền tự vận hành. Không chỉ là đầu tư, đây là một **Hệ Sinh Thái** liên kết bền vững.\n\n"
            "💎 *GIÁ TRỊ CỐT LÕI:*\n"
            "🔹 **Auto-Trading:** AI tự động tối ưu lợi nhuận.\n"
            "🔹 **7-Level Affiliate:** Cơ chế chia sẻ lợi nhuận 7 tầng duy nhất trên thị trường.\n"
            "🔹 **Transparency:** Minh bạch mọi giao dịch nạp/rút.\n"
            "🔹 **Sustainability:** Tái đầu tư bắt buộc để bảo vệ dòng tiền chung.\n\n"
            "🔥 *Cùng chúng tôi chinh phục kỷ nguyên số!* 🚀"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == '🚀 KIẾM LỢI NHUẬN':
        bot = await context.bot.get_me()
        link = f"https://t.me/{bot.username}?start={user_id}"
        msg = (
            "🚀 *TRUNG TÂM KHAI THÁC LỢI NHUẬN*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💰 *1. ĐẦU TƯ CÁ NHÂN (INVEST):*\n"
            "Lãi suất lên đến `7%/ngày`. Tiền về ví mỗi 24h.\n\n"
            "🤝 *2. ĐẾ CHẾ AFFILIATE (7 CẤP ĐỘ):*\n"
            "Nhận hoa hồng **TRÊN THU NHẬP** của hệ thống:\n"
            "🥇 **F1:** `40%`  🥈 **F2:** `35%`  🥉 **F3:** `30%` \n"
            "🏅 **F4:** `25%`  🏅 **F5:** `20%`  🏅 **F6:** `10%` \n"
            "🏅 **F7:** `5%` \n\n"
            f"🔗 *Link giới thiệu của bạn:*\n`{link}`\n\n"
            "📢 *Càng nhiều cấp dưới thu nhập cao, bạn càng giàu có!*"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 BẮT ĐẦU ĐẦU TƯ 📈", callback_data="invest_menu")],
            [InlineKeyboardButton("📤 CHIA SẺ LINK NGAY 🔗", switch_inline_query=f"\n🚀 Tham gia đế chế in tiền cùng tôi:\n👉 {link}")]
        ])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)

    elif text == '🎲 TRÒ CHƠI':
        txt, kb = game_main_menu()
        await update.message.reply_text(txt, parse_mode="Markdown", reply_markup=kb)

    elif text == '📅 ĐIỂM DANH':
        now = datetime.now()
        last_checkin_str = data[user_id].get("last_checkin")
        can_checkin = True
        
        if last_checkin_str:
            try:
                last_checkin = datetime.strptime(last_checkin_str, "%Y-%m-%d %H:%M:%S")
                if now < last_checkin + timedelta(hours=24):
                    can_checkin = False
                    time_left = (last_checkin + timedelta(hours=24)) - now
                    hours, remainder = divmod(time_left.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    await update.message.reply_text(f"⏳ Bạn đã điểm danh rồi! Vui lòng quay lại sau: *{hours} giờ {minutes} phút*.", parse_mode="Markdown")
            except: pass
        
        if can_checkin:
            data[user_id].setdefault("locked_balance", 0)
            data[user_id]["locked_balance"] += 150
            data[user_id]["last_checkin"] = now.strftime("%Y-%m-%d %H:%M:%S")
            log_transaction(data[user_id], 150, "Điểm danh hàng ngày (Ví Nạp)")
            save_data(data)
            await update.message.reply_text("🎉 *ĐIỂM DANH THÀNH CÔNG!*\n\n🎁 Bạn nhận được `+150đ` vào Ví Nạp. Hãy chăm chỉ quay lại vào ngày mai nhé!", parse_mode="Markdown")

    elif text == '🏆 ĐUA TOP BXH':
        bxh_msg = (
            "🏆 *BẢNG XẾP HẠNG ĐẠI GIA* 🏆\n\n"
            "✨ *THƯỞNG TOP TUẦN (Trao thưởng vào Thứ 7 hàng tuần):*\n"
            "🥇 Top 1: `50,000₫`\n"
            "🥈 Top 2: `30,000₫`\n"
            "🥉 Top 3: `15,000₫`\n\n"
            "🌟 *THƯỞNG TOP THÁNG (Trao thưởng Thứ 7 cuối tháng):*\n"
            "🥇 Top 1: `500,000₫`\n"
            "🥈 Top 2: `300,000₫`\n"
            "🥉 Top 3: `150,000₫`\n\n"
            "👇 *Vui lòng chọn hạng mục Đua Top bên dưới:*"
        )
        bxh_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Nạp Tuần", callback_data="bxh_nap_tuan"), InlineKeyboardButton("💸 Nạp Tháng", callback_data="bxh_nap_thang")],
            [InlineKeyboardButton("📈 Đầu Tư Tuần", callback_data="bxh_dautu_tuan"), InlineKeyboardButton("📈 Đầu Tư Tháng", callback_data="bxh_dautu_thang")],
            [InlineKeyboardButton("🎲 Cược Trò Chơi Tuần", callback_data="bxh_cuoc_tuan"), InlineKeyboardButton("🎲 Cược Trò Chơi Tháng", callback_data="bxh_cuoc_thang")],
            [InlineKeyboardButton("🤝 Tuyển Ref Tuần", callback_data="bxh_ref_tuan"), InlineKeyboardButton("🤝 Tuyển Ref Tháng", callback_data="bxh_ref_thang")]
        ])
        await update.message.reply_text(bxh_msg, parse_mode="Markdown", reply_markup=bxh_kb)

    elif text == '🏦 RÚT VỀ NGÂN HÀNG':
        u = data.get(user_id, {})
        req_wager = u.get('required_wager', 0)
        
        # LOGIC CHẶN HIT & RUN
        if req_wager > 0:
            await update.message.reply_text(f"❌ *RÚT TIỀN THẤT BẠI*\n\nĐể chống các hành vi gian lận và rửa tiền, hệ thống yêu cầu phát sinh doanh thu cược tương đương số tiền nạp.\n\n⚠️ Bạn cần cược thêm: *{req_wager:,} VNĐ* nữa mới đủ điều kiện rút tiền.", parse_mode="Markdown")
        elif u.get('balance', 0) < MIN_WITHDRAW:
            await update.message.reply_text(f"❌ *SỐ DƯ DƯỚI MỨC TỐI THIỂU*\nBạn cần đạt ít nhất {MIN_WITHDRAW:,} VNĐ để rút.")
        else:
            await update.message.reply_text(f"🏦 *YÊU CẦU RÚT TIỀN*\n\n💰 Số dư có thể rút: *{u.get('balance', 0):,} VNĐ*\n👉 Vui lòng nhập SỐ TIỀN bạn muốn rút (Tối thiểu {MIN_WITHDRAW:,}):", parse_mode="Markdown")
            context.user_data['state'] = "WAIT_WITHDRAW_AMOUNT"

    elif state == "WAIT_WITHDRAW_AMOUNT":
        try:
            amount = int(text)
            balance = data[user_id].get('balance', 0)
            if amount < MIN_WITHDRAW:
                await update.message.reply_text(f"❌ Số tiền rút tối thiểu là {MIN_WITHDRAW:,} VNĐ. Vui lòng nhập lại số tiền:")
            elif amount > balance:
                await update.message.reply_text(f"❌ Số dư không đủ! Bạn chỉ có {balance:,} VNĐ. Vui lòng nhập lại số tiền:")
            else:
                context.user_data['withdraw_amount'] = amount
                await update.message.reply_text("🏦 *THÔNG TIN NHẬN TIỀN*\nVui lòng nhập theo mẫu: `Ngân hàng - STK - Tên Chủ Thẻ`", parse_mode="Markdown")
                context.user_data['state'] = "WAIT_BANK"
        except ValueError:
            await update.message.reply_text("❌ Vui lòng chỉ nhập SỐ (Ví dụ: 50000). Vui lòng nhập lại số tiền:")

    elif state == "WAIT_BANK":
        amount = context.user_data.get('withdraw_amount', data[user_id].get('balance', 0))
        if data[user_id]['balance'] >= amount:
            data[user_id]['balance'] -= amount
            log_transaction(data[user_id], -amount, "Rút tiền về ngân hàng")
            save_data(data)
            
            notification_msg = (
                f"📥 *YÊU CẦU RÚT TIỀN*\n"
                f"👤 Đối tác: @{data[user_id]['username']}\n"
                f"🆔 ID: `{user_id}`\n"
                f"💰 Số tiền: *{amount:,} VNĐ*\n"
                f"🏦 Thông tin: `{text}`"
            )
            
            await context.bot.send_message(chat_id=GROUP_WITHDRAW_ID, text=notification_msg, parse_mode="Markdown")
            await update.message.reply_text("✅ *LỆNH RÚT THÀNH CÔNG!*\nYêu cầu đã được gửi tới bộ phận kế toán.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Lỗi: Số dư của bạn đã thay đổi. Vui lòng thực hiện lại lệnh rút tiền.")
        
        context.user_data['state'] = None
        context.user_data['withdraw_amount'] = None

    elif text == '🏦 NẠP TIỀN':
        qr_url = f"https://img.vietqr.io/image/{MY_BANK}-{MY_STK}-compact.jpg?addInfo=NAP{user_id}"
        msg = (f"🏦 *NẠP TIỀN VÀO HỆ THỐNG*\n━━━━━━━━━━━━━━\n👤 Chủ TK: *{MY_NAME}*\n💳 STK: `{MY_STK}`\n🏛 Ngân hàng: *{MY_BANK}*\n📝 Nội dung: `NAP{user_id}`\n\n⚠️ *Lưu ý:* Quét mã QR để chính xác 100%. Bấm xác nhận sau khi chuyển khoản thành công!")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ XÁC NHẬN ĐÃ CHUYỂN TIỀN", callback_data=f"confirm_nap_{user_id}")]])
        await update.message.reply_photo(photo=qr_url, caption=msg, parse_mode="Markdown", reply_markup=kb)

    elif text == '👤 TRANG CÁ NHÂN':
        u = data.get(user_id, {})
        inv_total = sum(i['amount'] for i in u.get('investments', []) if i['status'] == 'active')
        msg = (f"👤 *THÔNG TIN ĐỐI TÁC*\n━━━━━━━━━━━━━━\n🆔 ID: `{user_id}`\n💰 Ví rút: *{u.get('balance', 0):,}đ*\n🔒 Ví nạp: *{u.get('locked_balance', 0):,}đ*\n📈 Đang đầu tư: *{inv_total:,}đ*\n🤝 Tổng Ref: `{u.get('total_ref', 0)}` người")
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == '💳 VÍ CỦA TÔI':
        u = data.get(user_id, {})
        await update.message.reply_text(f"💳 *TÀI CHÍNH CÁ NHÂN*\n\n💰 Số dư rút được: *{u.get('balance', 0):,} VNĐ*\n🔒 Số dư cần cược: *{u.get('locked_balance', 0):,} VNĐ*", parse_mode="Markdown")

    elif text == '📊 THỐNG KÊ':
        msg = f"📊 *THỐNG KÊ HỆ THỐNG*\n\n👥 Tổng số đối tác: `{len(data)}` thành viên\n🏦 Trạng thái: Hoạt động tốt ✅"
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == '🆘 TRỢ GIÚP':
        await update.message.reply_text("🆘 *TRUNG TÂM HỖ TRỢ*\n\nMọi thắc mắc vui lòng liên hệ Admin:\n👉 @honghnt2747", parse_mode="Markdown")

    # --- CHỨC NĂNG NHẬT KÝ REF ---
    elif text == '📜 NHẬT KÝ REF' and int(user_id) == ADMIN_ID:
        await update.message.reply_text("📝 Nhập `ID_USER` để xem danh sách cấp dưới (F1) của họ:", parse_mode="Markdown")
        context.user_data['state'] = "WAIT_CHECK_REF"

    elif state == "WAIT_CHECK_REF" and int(user_id) == ADMIN_ID:
        target_id = text.strip()
        if target_id not in data:
            await update.message.reply_text("❌ Không tìm thấy ID này trong hệ thống.")
        else:
            target_user = data[target_id]
            f1_list = []
            for uid, u in data.items():
                if str(u.get("referrer")) == target_id:
                    f1_list.append((uid, u))
            
            if not f1_list:
                msg = f"👤 ID: `{target_id}` (@{target_user.get('username')})\nChưa mời được ai."
                await update.message.reply_text(msg, parse_mode="Markdown")
            else:
                msg = f"📜 *NHẬT KÝ REF CỦA ID {target_id}*\n"
                msg += f"Tổng số F1: {len(f1_list)}\n\n"
                
                for idx, (uid, u) in enumerate(f1_list, 1):
                    dep = u.get("total_deposit", 0)
                    paid = "✅ Đã nhận hoa hồng 500đ" if u.get("ref_reward_paid") else "❌ F1 chưa nạp đủ 1000đ"
                    uname = u.get("username", "Chưa có")
                    fname = u.get("first_name", uname)
                    jtime = u.get("joined", "Không xác định")
                    
                    entry = f"{idx}. Tên: {fname} | User: @{uname} | ID: `{uid}`\n └ Bấm /start: {jtime}\n └ Tổng nạp: {dep:,}đ [{paid}]\n\n"
                    
                    if len(msg) + len(entry) > 4000:
                        await update.message.reply_text(msg, parse_mode="Markdown")
                        msg = "" 
                        await asyncio.sleep(0.1) 
                    
                    msg += entry
                
                if msg: 
                    await update.message.reply_text(msg, parse_mode="Markdown")
        
        context.user_data['state'] = None
        
    # --- CHỨC NĂNG LỊCH SỬ GIAO DỊCH ---
    elif text == '🧾 LỊCH SỬ GIAO DỊCH' and int(user_id) == ADMIN_ID:
        await update.message.reply_text("📝 Nhập `ID_USER` để xem biến động số dư của người đó:", parse_mode="Markdown")
        context.user_data['state'] = "WAIT_CHECK_HISTORY"

    elif state == "WAIT_CHECK_HISTORY" and int(user_id) == ADMIN_ID:
        target_id = text.strip()
        if target_id not in data:
            await update.message.reply_text("❌ Không tìm thấy ID này trong hệ thống.")
        else:
            u = data[target_id]
            txs = u.get("transactions", [])
            if not txs:
                await update.message.reply_text(f"👤 ID `{target_id}` chưa phát sinh giao dịch nào.", parse_mode="Markdown")
            else:
                msg = f"🧾 *LỊCH SỬ GIAO DỊCH GẦN NHẤT: ID {target_id}*\n\n"
                for tx in reversed(txs):
                    sign = "+" if tx['amount'] > 0 else ""
                    entry = (f"🕒 {tx['time']}\n"
                             f"📝 N/D: {tx['reason']}\n"
                             f"💰 Tiền: {sign}{tx['amount']:,}đ\n"
                             f"💳 Ví rút: {tx['balance']:,}đ | Ví nạp: {tx['locked_balance']:,}đ\n"
                             + "➖" * 15 + "\n")
                    
                    if len(msg) + len(entry) > 4000:
                        await update.message.reply_text(msg, parse_mode="Markdown")
                        msg = ""
                        await asyncio.sleep(0.1)
                        
                    msg += entry
                
                if msg:
                    await update.message.reply_text(msg, parse_mode="Markdown")
        context.user_data['state'] = None

    # --- CHỨC NĂNG CHECK BUFF REF ---
    elif text == '🔍 CHECK BUFF REF' and int(user_id) == ADMIN_ID:
        ref_stats = {}
        for uid, u in data.items():
            ref = str(u.get("referrer"))
            if ref and ref != "None" and ref in data:
                if ref not in ref_stats:
                    ref_stats[ref] = {"total": 0, "fake": 0}
                ref_stats[ref]["total"] += 1
                if not u.get("ref_reward_paid"):
                    ref_stats[ref]["fake"] += 1
        
        sorted_stats = sorted(ref_stats.items(), key=lambda x: x[1]["fake"], reverse=True)[:10]
        msg = "🔍 *CẢNH BÁO BUFF REF (TOP 10)*\n_Danh sách các tài khoản mời nhiều người nhưng cấp dưới KHÔNG nạp tiền:_\n\n"
        found = False
        for uid, stats in sorted_stats:
            if stats["fake"] > 0:
                msg += f"👤 ID: `{uid}` - Mời: {stats['total']} người | Clone (Chưa nạp): {stats['fake']}\n"
                found = True
        
        if not found:
            msg = "✅ Hệ thống sạch, không có ai buff ref ảo."
        
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == '📢 PHÁT THÔNG BÁO' and int(user_id) == ADMIN_ID:
        await update.message.reply_text("📸 Gửi nội dung muốn ghim:")
        context.user_data['state'] = "WAIT_BC"

    elif state == "WAIT_BC" and int(user_id) == ADMIN_ID:
        status = await update.message.reply_text("📡 *HỆ THỐNG ĐANG ĐẨY THÔNG BÁO...*")
        count = 0
        for uid in data.keys():
            try:
                await context.bot.unpin_all_chat_messages(chat_id=int(uid))
                msg = await context.bot.copy_message(chat_id=int(uid), from_chat_id=update.message.chat_id, message_id=update.message.message_id)
                await context.bot.pin_chat_message(chat_id=int(uid), message_id=msg.message_id)
                count += 1
                await asyncio.sleep(0.1)
            except: continue
        await status.edit_text(f"✅ Đã cập nhật ghim cho {count} thành viên.")
        context.user_data['state'] = None

    elif text == '⚙️ QUẢN TRỊ: CỘNG TIỀN' and int(user_id) == ADMIN_ID:
        await update.message.reply_text("📝 Nhập: `ID_USER SỐ_TIỀN` (Tiền sẽ vào Ví Nạp)")
        context.user_data['state'] = "WAIT_ADD"

    elif state == "WAIT_ADD" and int(user_id) == ADMIN_ID:
        try:
            target, amount_add = text.split()
            amount_val = int(amount_add)
            data[target].setdefault("locked_balance", 0)
            data[target]['locked_balance'] += amount_val
            data[target].setdefault("required_wager", 0)
            data[target]["required_wager"] += amount_val
            
            data[target]["total_deposit"] = data[target].get("total_deposit", 0) + amount_val
            log_transaction(data[target], amount_val, "Admin cộng tiền tay (Ví Nạp)")
            update_stats(data[target], "deposit", amount_val)
            
            if data[target].get("referrer") and not data[target].get("ref_reward_paid") and data[target]["total_deposit"] >= 1000:
                ref_id = str(data[target]["referrer"])
                if ref_id in data and ref_id != target:
                    data[ref_id]["balance"] += REFERRAL_REWARD
                    data[ref_id]["total_ref"] = data[ref_id].get("total_ref", 0) + 1
                    data[target]["ref_reward_paid"] = True
                    log_transaction(data[ref_id], REFERRAL_REWARD, "Thưởng giới thiệu (F1 nạp đủ tiền)")
                    update_stats(data[ref_id], "ref", 1)
                    await pay_referral_commission(context, data, target, REFERRAL_REWARD, "tuyển Ref")
                    try: await context.bot.send_message(chat_id=int(ref_id), text=f"🎊 *MEMBER NẠP TIỀN:* +{REFERRAL_REWARD}đ thưởng trực tiếp từ F1!", parse_mode="Markdown")
                    except: pass

            save_data(data)
            await update.message.reply_text(f"✅ Đã cộng +{amount_val:,} VNĐ vào Ví Nạp cho `{target}`")
            try: await context.bot.send_message(chat_id=int(target), text=f"💰 Bạn được cộng +{amount_val:,} VNĐ vào Ví Nạp!")
            except: pass
        except: pass
        context.user_data['state'] = None
        
    elif text == '📉 THU HỒI SỐ DƯ' and int(user_id) == ADMIN_ID:
        await update.message.reply_text("📝 Nhập: `ID_USER SỐ_TIỀN` (hoặc `ID_USER ALL` để thu hồi toàn bộ số dư)")
        context.user_data['state'] = "WAIT_DEDUCT"

    elif state == "WAIT_DEDUCT" and int(user_id) == ADMIN_ID:
        try:
            parts = text.split()
            target = parts[0]
            amount_str = parts[1].upper()
            
            if target not in data:
                await update.message.reply_text("❌ Không tìm thấy ID này trong hệ thống.")
            else:
                data[target].setdefault("locked_balance", 0)
                data[target].setdefault("balance", 0)
                
                if amount_str == 'ALL':
                    total_revoked = data[target]['balance'] + data[target]['locked_balance']
                    data[target]['balance'] = 0
                    data[target]['locked_balance'] = 0
                    log_transaction(data[target], -total_revoked, "Admin thu hồi TOÀN BỘ số dư")
                    save_data(data)
                    await update.message.reply_text(f"✅ Đã thu hồi TOÀN BỘ (-{total_revoked:,} VNĐ) từ ID `{target}`")
                else:
                    amount_val = int(amount_str)
                    if data[target]['balance'] >= amount_val:
                        data[target]['balance'] -= amount_val
                    else:
                        rem = amount_val - data[target]['balance']
                        data[target]['balance'] = 0
                        if data[target]['locked_balance'] >= rem:
                            data[target]['locked_balance'] -= rem
                        else:
                            data[target]['locked_balance'] = 0
                    
                    log_transaction(data[target], -amount_val, "Admin thu hồi số dư")
                    save_data(data)
                    await update.message.reply_text(f"✅ Đã thu hồi -{amount_val:,} VNĐ từ ID `{target}`")
        except Exception as e: 
            await update.message.reply_text("❌ Lỗi cú pháp! Vui lòng nhập đúng định dạng: `ID_USER SỐ_TIỀN` hoặc `ID_USER ALL`")
        context.user_data['state'] = None

    elif state and state.startswith("WAIT_ADMIN_NAP_"):
        if int(user_id) != ADMIN_ID: return
        target_id = state.split("_")[3]
        try:
            amount = int(text)
            data[target_id].setdefault("locked_balance", 0)
            data[target_id]["locked_balance"] += amount
            data[target_id].setdefault("required_wager", 0)
            data[target_id]["required_wager"] += amount
            
            data[target_id]["total_deposit"] = data[target_id].get("total_deposit", 0) + amount
            log_transaction(data[target_id], amount, "Nạp tiền tự động duyệt thành công")
            update_stats(data[target_id], "deposit", amount)
            
            if data[target_id].get("referrer") and not data[target_id].get("ref_reward_paid") and data[target_id]["total_deposit"] >= 1000:
                ref_id = str(data[target_id]["referrer"])
                if ref_id in data and ref_id != target_id:
                    data[ref_id]["balance"] += REFERRAL_REWARD
                    data[ref_id]["total_ref"] = data[ref_id].get("total_ref", 0) + 1
                    data[target_id]["ref_reward_paid"] = True
                    log_transaction(data[ref_id], REFERRAL_REWARD, "Thưởng giới thiệu (F1 nạp đủ tiền)")
                    update_stats(data[ref_id], "ref", 1)
                    await pay_referral_commission(context, data, target_id, REFERRAL_REWARD, "tuyển Ref")

            save_data(data)
            await update.message.reply_text(f"✅ Đã nạp +{amount:,}đ vào Ví Nạp cho ID `{target_id}`")
            await context.bot.send_message(chat_id=int(target_id), text=f"✅ *NẠP TIỀN THÀNH CÔNG*\n\nTài khoản của bạn đã được cộng: +{amount:,} VNĐ 💰", parse_mode="Markdown")
        except: await update.message.reply_text("❌ Vui lòng chỉ nhập số tiền (Ví dụ: 100000)")
        context.user_data['state'] = None

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    data = load_data()
    u = data.get(user_id, {})
    await query.answer()

    if query.data == "ignore": return

    if query.data == "bxh_menu":
        bxh_msg = (
            "🏆 *BẢNG XẾP HẠNG ĐẠI GIA* 🏆\n\n"
            "✨ *THƯỞNG TOP TUẦN (Trao thưởng vào Thứ 7 hàng tuần):*\n"
            "🥇 Top 1: `50,000₫`\n"
            "🥈 Top 2: `30,000₫`\n"
            "🥉 Top 3: `15,000₫`\n\n"
            "🌟 *THƯỞNG TOP THÁNG (Trao thưởng Thứ 7 cuối tháng):*\n"
            "🥇 Top 1: `500,000₫`\n"
            "🥈 Top 2: `300,000₫`\n"
            "🥉 Top 3: `150,000₫`\n\n"
            "👇 *Vui lòng chọn hạng mục Đua Top bên dưới:*"
        )
        bxh_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Nạp Tuần", callback_data="bxh_nap_tuan"), InlineKeyboardButton("💸 Nạp Tháng", callback_data="bxh_nap_thang")],
            [InlineKeyboardButton("📈 Đầu Tư Tuần", callback_data="bxh_dautu_tuan"), InlineKeyboardButton("📈 Đầu Tư Tháng", callback_data="bxh_dautu_thang")],
            [InlineKeyboardButton("🎲 Cược Trò Chơi Tuần", callback_data="bxh_cuoc_tuan"), InlineKeyboardButton("🎲 Cược Trò Chơi Tháng", callback_data="bxh_cuoc_thang")],
            [InlineKeyboardButton("🤝 Tuyển Ref Tuần", callback_data="bxh_ref_tuan"), InlineKeyboardButton("🤝 Tuyển Ref Tháng", callback_data="bxh_ref_thang")]
        ])
        await query.edit_message_text(bxh_msg, parse_mode="Markdown", reply_markup=bxh_kb)
        return

    if query.data.startswith("bxh_"):
        parts = query.data.split("_")
        stat_type = parts[1] 
        period = parts[2]    
        
        now = datetime.now()
        curr_week = now.strftime("%Y-%V")
        curr_month = now.strftime("%Y-%m")
        
        leaderboard = []
        for uid, user_info in data.items():
            stats = user_info.get("stats", {})
            val = 0
            if period == "tuan" and stats.get("current_week") == curr_week:
                if stat_type == "nap": val = stats.get("week_deposit", 0)
                elif stat_type == "dautu": val = stats.get("week_invest", 0)
                elif stat_type == "cuoc": val = stats.get("week_bet", 0)
                elif stat_type == "ref": val = stats.get("week_ref", 0)
            elif period == "thang" and stats.get("current_month") == curr_month:
                if stat_type == "nap": val = stats.get("month_deposit", 0)
                elif stat_type == "dautu": val = stats.get("month_invest", 0)
                elif stat_type == "cuoc": val = stats.get("month_bet", 0)
                elif stat_type == "ref": val = stats.get("month_ref", 0)
            
            if val > 0:
                leaderboard.append((uid, user_info, val))
                
        leaderboard.sort(key=lambda x: x[2], reverse=True)
        top10 = leaderboard[:10]
        
        titles = {
            "nap_tuan": "💸 TOP NẠP TIỀN TUẦN", "nap_thang": "💸 TOP NẠP TIỀN THÁNG",
            "dautu_tuan": "📈 TOP ĐẦU TƯ TUẦN", "dautu_thang": "📈 TOP ĐẦU TƯ THÁNG",
            "cuoc_tuan": "🎲 TOP CƯỢC GAME TUẦN", "cuoc_thang": "🎲 TOP CƯỢC GAME THÁNG",
            "ref_tuan": "🤝 TOP TUYỂN REF TUẦN", "ref_thang": "🤝 TOP TUYỂN REF THÁNG"
        }
        
        msg = f"🏆 *{titles[f'{stat_type}_{period}']}* 🏆\n\n"
        if not top10:
            msg += "🌪 Trống vắng quá! Chưa có ai ghi danh trên bảng xếp hạng này. Hãy là người đầu tiên bứt phá nhé! 🚀"
        else:
            medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]
            for idx, (uid, user_info, val) in enumerate(top10):
                uname = user_info.get('first_name', 'Ẩn danh')
                display_val = f"{val:,}đ" if stat_type != "ref" else f"{val} người"
                msg += f"{medals[idx]} {uname} (`{uid}`): *{display_val}*\n"
                
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại Bảng Xếp Hạng", callback_data="bxh_menu")]])
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    if query.data == "check_join":
        if await is_subscribed(context, query.from_user.id):
            await query.message.delete()
            welcome_msg = (
                f"🌟 *KÍNH CHÀO ĐỐI TÁC: {query.from_user.first_name.upper()}*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🏦 *Chào mừng bạn đến với Cỗ Máy In Tiền v3.0*\n"
                "Hệ thống vận hành tài chính phi tập trung tự động hàng đầu trên Telegram.\n\n"
                "⚡️ *CƠ CHẾ VẬN HÀNH ĐỘC QUYỀN:*\n"
                "▪️ **Lợi nhuận thụ động:** Trả thẳng vào ví lên tới `7%/ngày`.\n"
                "▪️ **Đế chế Affiliate:** Chia sẻ hoa hồng 7 tầng trên tổng thu nhập.\n"
                "▪️ **Bảo mật tuyệt đối:** Thanh khoản chớp nhoáng, dòng tiền minh bạch.\n\n"
                "👇 *Hệ thống đã được kích hoạt. Hãy thao tác trên thanh Menu bên dưới để bắt đầu chuỗi ngày bùng nổ lợi nhuận!* 💸"
            )
            await context.bot.send_message(chat_id=query.from_user.id, text=welcome_msg, parse_mode="Markdown", reply_markup=main_menu(query.from_user.id))
        else: await query.answer("❌ Lỗi hệ thống: Vui lòng tham gia đầy đủ các kênh bảo chứng!", show_alert=True)

    elif query.data == "invest_menu":
        text = "📉 *DANH SÁCH GÓI ĐẦU TƯ*\n\n"
        btns = []
        for i, p in enumerate(INVEST_PACKS):
            text += f"{p['icon']} *Gói {i+1}:* >{p['min']:,}đ | Lãi: `{round(p['interest']*100, 1)}%/ngày`\n"
            btns.append([InlineKeyboardButton(f"{p['icon']} Đầu Tư Gói {p['min']:,}đ", callback_data=f"buy_{i}")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))

    elif query.data.startswith("buy_"):
        idx = int(query.data.split("_")[1])
        pack = INVEST_PACKS[idx]
        u.setdefault("locked_balance", 0)
        total_bal = u["balance"] + u["locked_balance"]
        if total_bal < pack["min"]:
            await query.message.reply_text("❌ Số dư không đủ!")
            return
        
        deduct = pack["min"]
        if u["locked_balance"] >= deduct:
            u["locked_balance"] -= deduct
        else:
            rem = deduct - u["locked_balance"]
            u["locked_balance"] = 0
            u["balance"] -= rem

        new_inv = {"amount": pack["min"], "interest": pack["interest"], "days_left": pack["days"], "start_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "last_payment": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": "active", "notified_task": False}
        if "investments" not in u: u["investments"] = []
        u["investments"].append(new_inv)
        log_transaction(u, -pack["min"], f"Đầu tư gói sinh lời {pack['min']:,}đ")
        update_stats(u, "invest", pack["min"])
        save_data(data)
        await query.message.reply_text(f"✅ Đầu tư thành công!", parse_mode="Markdown")

    # ---- ĐIỀU HƯỚNG MỤC TRÒ CHƠI ----
    elif query.data == "open_game_main":
        t, k = game_main_menu()
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    elif query.data == "open_game_dice":
        u["current_game"] = "dice"
        save_data(data)
        t, k = game_menu_dice(user_id, data)
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    elif query.data == "open_game_slot":
        u["current_game"] = "slot"
        save_data(data)
        t, k = game_menu_slot(user_id, data)
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    elif query.data == "open_game_bb":
        u["current_game"] = "bb"
        save_data(data)
        t, k = game_menu_bb(user_id, data)
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    elif query.data == "open_game_fb":
        u["current_game"] = "fb"
        save_data(data)
        t, k = game_menu_fb(user_id, data)
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    elif query.data == "open_game_dart":
        u["current_game"] = "dart"
        save_data(data)
        t, k = game_menu_dart(user_id, data)
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    elif query.data == "open_game_baucua":
        u["current_game"] = "baucua"
        save_data(data)
        t, k = game_menu_baucua(user_id, data)
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    elif query.data == "g_refresh":
        cg = u.get("current_game")
        if cg == "slot": t, k = game_menu_slot(user_id, data)
        elif cg == "bb": t, k = game_menu_bb(user_id, data)
        elif cg == "fb": t, k = game_menu_fb(user_id, data)
        elif cg == "dart": t, k = game_menu_dart(user_id, data)
        elif cg == "baucua": t, k = game_menu_baucua(user_id, data)
        else: t, k = game_menu_dice(user_id, data)
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    elif query.data.startswith("g_"):
        val = query.data.split("_")[1]
        u.setdefault("locked_balance", 0)
        u.setdefault("bet", 0)
        
        if val == "clear":
            u["bet"] = 0
            if u.get("current_game") == "baucua":
                u["bc_doors"] = []
            save_data(data)
            
            cg = u.get("current_game")
            if cg == "slot": t, k = game_menu_slot(user_id, data)
            elif cg == "bb": t, k = game_menu_bb(user_id, data)
            elif cg == "fb": t, k = game_menu_fb(user_id, data)
            elif cg == "dart": t, k = game_menu_dart(user_id, data)
            elif cg == "baucua": t, k = game_menu_baucua(user_id, data)
            else: t, k = game_menu_dice(user_id, data)
            try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
            except: pass
            return

        if val == "all":
            # Nếu là bầu cua và chọn nhiều cửa, số tiền chia đều hoặc tùy logic. Ở đây lấy tổng tiền.
            doors_len = len(u.get("bc_doors", []))
            if u.get("current_game") == "baucua" and doors_len > 0:
                max_bet_per_door = (u["balance"] + u["locked_balance"]) // doors_len
                u["bet"] = max_bet_per_door
            else:
                u["bet"] = u["balance"] + u["locked_balance"]
        else: 
            try: u["bet"] += int(val)
            except: u["bet"] = 0
        
        # Kiểm tra tiền đối với bầu cua (cược x số cửa)
        doors_len = len(u.get("bc_doors", [])) if u.get("current_game") == "baucua" else 1
        total_needed = u["bet"] * max(1, doors_len)
        
        if total_needed > (u["balance"] + u["locked_balance"]):
            u["bet"] = 0
            await query.answer("❌ Không đủ tiền!", show_alert=True)
        else:
            save_data(data)
            cg = u.get("current_game")
            if cg == "slot": t, k = game_menu_slot(user_id, data)
            elif cg == "bb": t, k = game_menu_bb(user_id, data)
            elif cg == "fb": t, k = game_menu_fb(user_id, data)
            elif cg == "dart": t, k = game_menu_dart(user_id, data)
            elif cg == "baucua": t, k = game_menu_baucua(user_id, data)
            else: t, k = game_menu_dice(user_id, data)
            try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
            except: pass

    elif query.data.startswith("gs_"):
        parts = query.data.split("_")
        
        # Logic chọn cửa cho Bầu Cua (có thể chọn nhiều cửa)
        if parts[1] == "bc":
            door_val = parts[2]
            u.setdefault("bc_doors", [])
            if door_val in u["bc_doors"]:
                u["bc_doors"].remove(door_val)
            else:
                u["bc_doors"].append(door_val)
            
            # Kiểm tra lại tổng tiền nếu chọn thêm cửa
            total_needed = u.get("bet", 0) * len(u["bc_doors"])
            if total_needed > (u["balance"] + u["locked_balance"]):
                u["bc_doors"].remove(door_val)
                await query.answer("❌ Không đủ tiền cược cho số cửa này!", show_alert=True)
            else:
                save_data(data)
                t, k = game_menu_baucua(user_id, data)
                try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
                except: pass
            return

        # Logic chọn cửa cho Tài xỉu
        u["side"] = parts[1]
        save_data(data)
        t, k = game_menu_dice(user_id, data)
        try: await query.edit_message_text(t, reply_markup=k, parse_mode="Markdown")
        except: pass

    # ==========================================================
    # --- XỬ LÝ KẾT QUẢ TỪNG GAME ---
    # ==========================================================
    
    # 0. BẦU CUA DÂN GIAN
    elif query.data == "gp_baucua":
        bet_per_door = u.get("bet", 0)
        doors = u.get("bc_doors", [])
        
        if bet_per_door <= 0 or not doors:
            return await query.answer("⚠️ Hãy chọn mức cược và ít nhất 1 cửa!", show_alert=True)
            
        total_bet = bet_per_door * len(doors)
        if u["locked_balance"] >= total_bet: 
            u["locked_balance"] -= total_bet
        else:
            rem = total_bet - u["locked_balance"]
            u["locked_balance"] = 0
            u["balance"] -= rem

        if u.get("required_wager", 0) > 0:
            u["required_wager"] = max(0, u["required_wager"] - total_bet)
        
        log_transaction(u, -total_bet, f"Cược Bầu Cua ({len(doors)} cửa)")
        update_stats(u, "bet", total_bet)
        
        await query.message.delete()
        msg_status = await context.bot.send_message(chat_id=query.message.chat.id, text="🎲 *Đang xóc Bầu Cua...*", parse_mode="Markdown")
        
        # Tung 3 viên xúc xắc
        results = []
        for _ in range(3):
            dice = await context.bot.send_dice(chat_id=query.message.chat.id)
            results.append(dice.dice.value)
            await asyncio.sleep(1) # Chờ mỗi viên tung xong
            
        await asyncio.sleep(1.5)
        try: await context.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_status.message_id)
        except: pass

        # Tính kết quả
        total_win = 0
        res_text = ""
        for r in results:
            item = BOU_CUA_MAP[r]
            res_text += f"{item['emoji']} "
            if str(r) in doors:
                total_win += int(bet_per_door * 1.8)

        if total_win > 0:
            u["balance"] += total_win
            log_transaction(u, total_win, "Thắng Bầu Cua")
            msg = f"🥳 **THẮNG RỒI!**\nKết quả: {res_text}\n+ {total_win:,}đ vào Ví Rút."
        else:
            msg = f"💸 **THUA!**\nKết quả: {res_text}\n- {total_bet:,}đ"
        
        u["bet"] = 0
        u["bc_doors"] = []
        save_data(data)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Chơi tiếp", callback_data="g_refresh")]])
        await context.bot.send_message(chat_id=query.message.chat.id, text=msg, reply_markup=kb, parse_mode="Markdown")


    # 1. QUAY SLOT (NỔ HŨ)
    elif query.data == "gp_slot":
        bet = u.get("bet", 0)
        if bet <= 0: return await query.answer("⚠️ Hãy chọn mức cược trước khi quay Hũ!", show_alert=True)
        
        if u["locked_balance"] >= bet: u["locked_balance"] -= bet
        else:
            rem = bet - u["locked_balance"]
            u["locked_balance"] = 0
            u["balance"] -= rem

        if u.get("required_wager", 0) > 0:
            u["required_wager"] = max(0, u["required_wager"] - bet)
        
        log_transaction(u, -bet, f"Cược Quay Hũ (Slot)")
        update_stats(u, "bet", bet)
        
        await query.message.delete()
        msg_status = await context.bot.send_message(chat_id=query.message.chat.id, text="🎰 *Đang quay hũ... Chúc bạn may mắn!*", parse_mode="Markdown")
        dice = await context.bot.send_dice(chat_id=query.message.chat.id, emoji="🎰")
        val = dice.dice.value
        
        await asyncio.sleep(2.5)
        try: await context.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_status.message_id)
        except: pass

        if val == 64:
            win = bet * 10
            u["balance"] += win
            log_transaction(u, win, "JACKPOT 777 Slot")
            msg = f"🎉 **JACKPOT! 7️⃣7️⃣7️⃣** 🎉\nNổ hũ siêu to khổng lồ! +{win:,}đ vào Ví Rút."
        elif val in [1, 22, 43]:
            win = bet * 5
            u["balance"] += win
            log_transaction(u, win, "Thắng Slot")
            msg = f"🥳 **BINGO!** Trúng 3 hình giống nhau!\n+ {win:,}đ vào Ví Rút."
        else:
            msg = f"💸 Tạch rồi! Trượt hũ.\n- {bet:,}đ"
        
        u["bet"] = 0
        save_data(data)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Quay tiếp", callback_data="g_refresh")]])
        await context.bot.send_message(chat_id=query.message.chat.id, text=msg, reply_markup=kb, parse_mode="Markdown")

    # 2. BÓNG RỔ (BASKETBALL)
    elif query.data == "gp_bb":
        bet = u.get("bet", 0)
        if bet <= 0: return await query.answer("⚠️ Hãy chọn mức cược!", show_alert=True)
        
        if u["locked_balance"] >= bet: u["locked_balance"] -= bet
        else:
            rem = bet - u["locked_balance"]
            u["locked_balance"] = 0
            u["balance"] -= rem

        if u.get("required_wager", 0) > 0:
            u["required_wager"] = max(0, u["required_wager"] - bet)
        
        log_transaction(u, -bet, f"Cược Bóng Rổ")
        update_stats(u, "bet", bet)
        
        await query.message.delete()
        msg_status = await context.bot.send_message(chat_id=query.message.chat.id, text="🏀 *Cầu thủ đang ném bóng...*", parse_mode="Markdown")
        dice = await context.bot.send_dice(chat_id=query.message.chat.id, emoji="🏀")
        val = dice.dice.value
        
        await asyncio.sleep(4)
        try: await context.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_status.message_id)
        except: pass

        # Telegram Basketball: 4, 5 là vào rổ
        if val in [4, 5]:
            win = bet * 2
            u["balance"] += win
            log_transaction(u, win, "Thắng Bóng Rổ")
            msg = f"🎯 **VÀOOOO RỔ!** Cú ném quá đẹp mắt!\n+ {win:,}đ vào Ví Rút."
        else:
            msg = f"💨 Tạch rồi! Bóng bay ra ngoài hoặc kẹt vành.\n- {bet:,}đ"
        
        u["bet"] = 0
        save_data(data)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Ném tiếp", callback_data="g_refresh")]])
        await context.bot.send_message(chat_id=query.message.chat.id, text=msg, reply_markup=kb, parse_mode="Markdown")

    # 3. BÓNG ĐÁ (FOOTBALL)
    elif query.data == "gp_fb":
        bet = u.get("bet", 0)
        if bet <= 0: return await query.answer("⚠️ Hãy chọn mức cược!", show_alert=True)
        
        if u["locked_balance"] >= bet: u["locked_balance"] -= bet
        else:
            rem = bet - u["locked_balance"]
            u["locked_balance"] = 0
            u["balance"] -= rem

        if u.get("required_wager", 0) > 0:
            u["required_wager"] = max(0, u["required_wager"] - bet)
        
        log_transaction(u, -bet, f"Cược Bóng Đá")
        update_stats(u, "bet", bet)
        
        await query.message.delete()
        msg_status = await context.bot.send_message(chat_id=query.message.chat.id, text="⚽️ *Đang lấy đà sút phạt...*", parse_mode="Markdown")
        dice = await context.bot.send_dice(chat_id=query.message.chat.id, emoji="⚽")
        val = dice.dice.value
        
        await asyncio.sleep(4)
        try: await context.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_status.message_id)
        except: pass

        # Telegram Football: 3, 4, 5 là vào gôn
        if val in [3, 4, 5]:
            win = int(bet * 1.5)
            u["balance"] += win
            log_transaction(u, win, "Thắng Bóng Đá")
            msg = f"🥅 **VÀOOOO!** Bàn thắng tuyệt đẹp!\n+ {win:,}đ vào Ví Rút."
        else:
            msg = f"🧤 Xui quá! Thủ môn bắt được hoặc sút ra ngoài.\n- {bet:,}đ"
        
        u["bet"] = 0
        save_data(data)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Sút tiếp", callback_data="g_refresh")]])
        await context.bot.send_message(chat_id=query.message.chat.id, text=msg, reply_markup=kb, parse_mode="Markdown")

    # 4. PHI TIÊU (DART)
    elif query.data == "gp_dart":
        bet = u.get("bet", 0)
        if bet <= 0: return await query.answer("⚠️ Hãy chọn mức cược!", show_alert=True)
        
        if u["locked_balance"] >= bet: u["locked_balance"] -= bet
        else:
            rem = bet - u["locked_balance"]
            u["locked_balance"] = 0
            u["balance"] -= rem

        if u.get("required_wager", 0) > 0:
            u["required_wager"] = max(0, u["required_wager"] - bet)
        
        log_transaction(u, -bet, f"Cược Phi Tiêu")
        update_stats(u, "bet", bet)
        
        await query.message.delete()
        msg_status = await context.bot.send_message(chat_id=query.message.chat.id, text="🎯 *Đang ngắm chuẩn hồng tâm...*", parse_mode="Markdown")
        dice = await context.bot.send_dice(chat_id=query.message.chat.id, emoji="🎯")
        val = dice.dice.value
        
        await asyncio.sleep(3)
        try: await context.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_status.message_id)
        except: pass

        # Telegram Dart: 6 là trúng giữa tâm (Bullseye), 5 là vòng kế tiếp
        if val == 6:
            win = bet * 3
            u["balance"] += win
            log_transaction(u, win, "Bullseye Phi Tiêu")
            msg = f"🔴 **BULLSEYE!** Trúng ngay hồng tâm x3 tiền!\n+ {win:,}đ vào Ví Rút."
        elif val == 5:
            win = int(bet * 1.5)
            u["balance"] += win
            log_transaction(u, win, "Thắng Phi Tiêu")
            msg = f"🎯 **ĐẸP MẮT!** Trúng vòng trong.\n+ {win:,}đ vào Ví Rút."
        else:
            msg = f"💨 Tạch! Lệch tâm mất rồi.\n- {bet:,}đ"
        
        u["bet"] = 0
        save_data(data)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Ném tiếp", callback_data="g_refresh")]])
        await context.bot.send_message(chat_id=query.message.chat.id, text=msg, reply_markup=kb, parse_mode="Markdown")

    # 5. XÚC XẮC (CHẴN LẺ TÀI XỈU)
    elif query.data == "gp_roll":
        bet = u.get("bet", 0)
        side = u.get("side")
        if bet <= 0 or not side:
            await query.answer("⚠️ Hãy chọn mức cược và cửa!", show_alert=True)
            return
        
        if u["locked_balance"] >= bet: u["locked_balance"] -= bet
        else:
            rem = bet - u["locked_balance"]
            u["locked_balance"] = 0
            u["balance"] -= rem

        if u.get("required_wager", 0) > 0:
            u["required_wager"] = max(0, u["required_wager"] - bet)
        
        log_transaction(u, -bet, f"Cược Game Xúc Xắc ({side})")
        update_stats(u, "bet", bet)
        
        await query.message.delete()
        msg_status = await context.bot.send_message(chat_id=query.message.chat.id, text="🎲 *Hệ thống đang lắc xúc xắc...*", parse_mode="Markdown")
        dice = await context.bot.send_dice(chat_id=query.message.chat.id)
        val = dice.dice.value
        
        await asyncio.sleep(3.5)
        try: await context.bot.delete_message(chat_id=query.message.chat.id, message_id=msg_status.message_id)
        except: pass

        actual_win = False
        if side == "chan" and val % 2 == 0: actual_win = True
        elif side == "le" and val % 2 != 0: actual_win = True
        elif side == "tai" and val >= 4: actual_win = True
        elif side == "xiu" and val <= 3: actual_win = True

        res_text = "CHẴN" if val % 2 == 0 else "LẺ"
        res_text += " - TÀI" if val >= 4 else " - XỈU"

        if actual_win:
            win = int(bet * 1.8)
            u["balance"] += win
            log_transaction(u, win, "Thắng Game Xúc Xắc")
            msg = f"🥳 THẮNG! Xúc xắc: {val} ({res_text})\n+ {win:,}đ vào Ví Rút."
        else:
            msg = f"💸 THUA! Xúc xắc: {val} ({res_text})\n- {bet:,}đ"
        
        u["bet"] = 0
        u["side"] = None
        save_data(data)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Chơi tiếp", callback_data="g_refresh")]])
        await context.bot.send_message(chat_id=query.message.chat.id, text=msg, reply_markup=kb)

    elif query.data.startswith("confirm_nap_"):
        uid = query.data.split("_")[2]
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🔔 *NẠP TIỀN:* ID `{uid}` báo chuyển khoản.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ DUYỆT NGAY", callback_data=f"admin_nap_{uid}")]]))
        await query.edit_message_caption(caption="✅ Chờ Admin xác nhận...", parse_mode="Markdown")

    elif query.data.startswith("admin_nap_"):
        uid = query.data.split("_")[2]
        context.user_data['state'] = f"WAIT_ADMIN_NAP_{uid}"
        await query.message.reply_text(f"💰 Nhập số tiền cho ID `{uid}`:")

async def is_subscribed(context, user_id):
    if user_id == ADMIN_ID: return True
    for channel in REQUIRED_CHANNELS:
        try:
            m = await context.bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
            if m.status in ['left', 'kicked']: return False
        except: return False
    return True

def force_join_keyboard():
    btns = [[InlineKeyboardButton(f"🔔 {c['name']}", url=c['url'])] for c in REQUIRED_CHANNELS]
    btns.append([InlineKeyboardButton("✅ XÁC THỰC", callback_data="check_join")])
    return InlineKeyboardMarkup(btns)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("send", admin_send_command))
    if app.job_queue: app.job_queue.run_repeating(daily_interest_job, interval=600, first=10)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_all))
    print("Bot v3.0 running...")
    app.run_polling(drop_pending_updates=True)
