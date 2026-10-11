import io
import math
from typing import List
from PIL import Image, ImageDraw, ImageFont
from engine.models import GameSession, ExecutivePower, Policy

def get_font(size: int, bold: bool = False):
    """Спроба завантажити системний шрифт або дефолтний."""
    font_names = ["segoeui.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
    if bold:
        font_names = ["segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
    
    for name in font_names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def draw_danger_badge(draw: ImageDraw.Draw, cx: int, cy: int, size: int = 14, fill_color=(255, 215, 80)):
    """Малює векторний трикутник небезпеки з вигуком всередині (гарантовано без квадратів шрифту)."""
    h = size
    w = int(size * 1.15)
    points = [
        (cx, cy - h // 2),
        (cx - w // 2, cy + h // 2),
        (cx + w // 2, cy + h // 2)
    ]
    draw.polygon(points, fill=fill_color)
    draw.line([(cx, cy - h // 6), (cx, cy + h // 6)], fill=(35, 15, 10), width=2)
    draw.point([(cx, cy + h // 3), (cx + 1, cy + h // 3)], fill=(35, 15, 10))

def get_slot_powers(player_count: int) -> List[str]:
    """Повертає підписи повноважень для 6 фашистських слотів за кількістю гравців."""
    if player_count in (5, 6):
        return [
            "",
            "",
            "ПОЛІТИКА\n(Перегляд 3 карт)",
            "СТРАТА\n(Вирок суду)",
            "СТРАТА\n+ ПРАВО ВЕТО",
            "ФАШИЗМ\n(ПЕРЕМОГА)"
        ]
    elif player_count in (7, 8):
        return [
            "",
            "ПЕРЕВІРКА\nЛОЯЛЬНОСТІ",
            "ПОЗАЧЕРГОВІ\nВИБОРИ",
            "СТРАТА\n(Вирок суду)",
            "СТРАТА\n+ ПРАВО ВЕТО",
            "ФАШИЗМ\n(ПЕРЕМОГА)"
        ]
    else: # 9-10 гравців
        return [
            "ПЕРЕВІРКА\nЛОЯЛЬНОСТІ",
            "ПЕРЕВІРКА\nЛОЯЛЬНОСТІ",
            "ПОЗАЧЕРГОВІ\nВИБОРИ",
            "СТРАТА\n(Вирок суду)",
            "СТРАТА\n+ ПРАВО ВЕТО",
            "ФАШИЗМ\n(ПЕРЕМОГА)"
        ]

def get_slot_action_name(player_count: int, slot_idx: int) -> str:
    """Повертає чітку назву виконаної дії для ухваленого фашистського закону."""
    if player_count in (5, 6):
        actions = [
            "",
            "",
            "ПЕРЕГЛЯД 3 КАРТ",
            "СТРАТА ДЕПУТАТА",
            "СТРАТА + ВЕТО",
            "ФАШИЗМ (ПЕРЕМОГА)"
        ]
    elif player_count in (7, 8):
        actions = [
            "",
            "ПЕРЕВІРКА ЛОЯЛЬНОСТІ",
            "ПОЗАЧЕРГОВІ ВИБОРИ",
            "СТРАТА ДЕПУТАТА",
            "СТРАТА + ВЕТО",
            "ФАШИЗМ (ПЕРЕМОГА)"
        ]
    else: # 9-10 гравців
        actions = [
            "ПЕРЕВІРКА ЛОЯЛЬНОСТІ",
            "ПЕРЕВІРКА ЛОЯЛЬНОСТІ",
            "ПОЗАЧЕРГОВІ ВИБОРИ",
            "СТРАТА ДЕПУТАТА",
            "СТРАТА + ВЕТО",
            "ФАШИЗМ (ПЕРЕМОГА)"
        ]
    return actions[slot_idx] if slot_idx < len(actions) else ""

def render_board_image(game: GameSession) -> io.BytesIO:
    """
    Генерує Kickstarter-стилізований планшет із поточним станом гри:
    - Ліберальний трек (5 слотів)
    - Фашистський трек (6 слотів із повноваженнями, виділеною ЗОНОЮ ГІТЛЕРА та примітками)
    - Лічильник виборів / кризи влади (0..3)
    """
    width = 1100
    height = 760
    
    # Базовий фон: глибокий темно-дерев'яний (Mahogany)
    img = Image.new("RGBA", (width, height), color=(22, 17, 15, 255))
    draw = ImageDraw.Draw(img)

    # Вінтажні декоративні рамки з кутовими акцентами
    draw.rectangle([14, 14, width - 14, height - 14], outline=(175, 135, 65), width=3)
    draw.rectangle([20, 20, width - 20, height - 20], outline=(70, 50, 35), width=2)

    font_title = get_font(26, bold=True)
    font_sub = get_font(17, bold=True)
    font_card = get_font(13, bold=True)
    font_card_sub = get_font(11, bold=False)
    font_banner = get_font(13, bold=True)
    font_zone = get_font(12, bold=True)

    # 1. ЗАГОЛОВОК
    title_text = "REICHSTAG — СТАН ПАРЛАМЕНТУ"
    draw.text((width // 2, 42), title_text, fill=(235, 215, 175), font=font_title, anchor="mm")

    # 2. ЛІБЕРАЛЬНИЙ ТРЕК (LIBERAL TRACK)
    lib_y = 75
    draw.rounded_rectangle([40, lib_y, width - 40, lib_y + 185], radius=10, fill=(28, 48, 74), outline=(70, 120, 180), width=2)
    draw.text((60, lib_y + 18), "DIE LIBERALEN — ПЛАНШЕТ СВОБОДИ (5 для перемоги)", fill=(160, 200, 255), font=font_sub)

    slot_w = 175
    slot_h = 125
    slot_y = lib_y + 45
    spacing_x = 25
    start_x_lib = (width - (5 * slot_w + 4 * spacing_x)) // 2

    for i in range(5):
        sx = start_x_lib + i * (slot_w + spacing_x)
        is_enacted = i < game.enacted_liberal

        if is_enacted:
            # Ухвалений ліберальний закон
            draw.rounded_rectangle([sx, slot_y, sx + slot_w, slot_y + slot_h], radius=8, fill=(45, 105, 180), outline=(210, 230, 255), width=3)
            draw.text((sx + slot_w // 2, slot_y + 32), "• LIBERAL •", fill=(210, 235, 255), font=font_card, anchor="mm")
            draw.text((sx + slot_w // 2, slot_y + 62), "LIBERALES", fill=(255, 255, 255), font=font_card, anchor="mm")
            draw.text((sx + slot_w // 2, slot_y + 82), "GESETZ", fill=(200, 225, 255), font=font_card, anchor="mm")
            draw.text((sx + slot_w // 2, slot_y + 107), f"#{i+1} УХВАЛЕНО", fill=(140, 240, 140), font=font_card_sub, anchor="mm")
        else:
            # Порожній слот
            draw.rounded_rectangle([sx, slot_y, sx + slot_w, slot_y + slot_h], radius=8, fill=(18, 30, 48), outline=(60, 90, 130), width=2)
            draw.text((sx + slot_w // 2, slot_y + 50), f"Слот {i+1}", fill=(90, 120, 160), font=font_card, anchor="mm")
            draw.text((sx + slot_w // 2, slot_y + 75), "(Порожньо)", fill=(70, 95, 130), font=font_card_sub, anchor="mm")

    # 3. ФАШИСТСЬКИЙ ТРЕК (FASCIST TRACK)
    fasc_y = 275
    fasc_h = 295
    is_hitler_zone_active = (game.enacted_fascist >= 3)

    # Рамка фашистського треку
    draw.rounded_rectangle([40, fasc_y, width - 40, fasc_y + fasc_h], radius=10, fill=(58, 22, 22), outline=(170, 60, 60), width=2)
    draw.text((60, fasc_y + 18), "DIE FASCHISTEN — ПЛАНШЕТ ДИКТАТУРИ (6 для перемоги)", fill=(255, 170, 170), font=font_sub)

    slot_w_f = 148
    spacing_x_f = 18
    start_x_fasc = (width - (6 * slot_w_f + 5 * spacing_x_f)) // 2
    slot_y_f = fasc_y + 48
    slot_h_f = 170

    player_count = len(game.players) if game.players else 6
    powers = get_slot_powers(player_count)

    # 3.1 ОСОБЛИВИЙ ВИГЛЯД: ЗОНА ГІТЛЕРА (Слоти 4, 5, 6 -> індекси 3, 4, 5)
    hz_start_x = start_x_fasc + 3 * (slot_w_f + spacing_x_f) - 8
    hz_end_x = start_x_fasc + 5 * (slot_w_f + spacing_x_f) + slot_w_f + 8
    hz_y1 = slot_y_f - 6
    hz_y2 = slot_y_f + slot_h_f + 6

    if is_hitler_zone_active:
        # АКТИВНА ЗОНА ГІТЛЕРА (після 3 законів)
        draw.rounded_rectangle(
            [hz_start_x, hz_y1, hz_end_x, hz_y2],
            radius=10,
            fill=(80, 18, 18),
            outline=(255, 65, 65),
            width=3
        )
        badge_w = 430
        badge_x1 = (hz_start_x + hz_end_x - badge_w) // 2
        badge_x2 = badge_x1 + badge_w
        draw.rounded_rectangle(
            [badge_x1, hz_y1 - 12, badge_x2, hz_y1 + 10],
            radius=6,
            fill=(210, 35, 35),
            outline=(255, 220, 100),
            width=2
        )
        draw_danger_badge(draw, badge_x1 + 16, hz_y1 - 1, size=13, fill_color=(255, 235, 140))
        draw_danger_badge(draw, badge_x2 - 16, hz_y1 - 1, size=13, fill_color=(255, 235, 140))
        draw.text(
            ((hz_start_x + hz_end_x) // 2, hz_y1 - 1),
            "ЗОНА ГІТЛЕРА АКТИВНА! НЕ ДОПУСТІТЬ ГІТЛЕРА В КАНЦЛЕРИ!",
            fill=(255, 255, 240),
            font=font_zone,
            anchor="mm"
        )
    else:
        # НЕАКТИВНА ЗОНА ГІТЛЕРА (попередження)
        draw.rounded_rectangle(
            [hz_start_x, hz_y1, hz_end_x, hz_y2],
            radius=10,
            fill=(42, 16, 16),
            outline=(180, 90, 50),
            width=2
        )
        badge_w = 380
        badge_x1 = (hz_start_x + hz_end_x - badge_w) // 2
        badge_x2 = badge_x1 + badge_w
        draw.rounded_rectangle(
            [badge_x1, hz_y1 - 11, badge_x2, hz_y1 + 9],
            radius=6,
            fill=(70, 30, 20),
            outline=(210, 130, 60),
            width=1
        )
        draw_danger_badge(draw, badge_x1 + 15, hz_y1 - 1, size=12, fill_color=(250, 190, 100))
        draw_danger_badge(draw, badge_x2 - 15, hz_y1 - 1, size=12, fill_color=(250, 190, 100))
        draw.text(
            ((hz_start_x + hz_end_x) // 2, hz_y1 - 1),
            "HITLER ZONE (АКТИВУЄТЬСЯ ПІСЛЯ 3-ГО ЗАКОНУ)",
            fill=(245, 190, 120),
            font=font_zone,
            anchor="mm"
        )

    # 3.2 МАЛЮВАННЯ СЛОТІВ
    for i in range(6):
        sx = start_x_fasc + i * (slot_w_f + spacing_x_f)
        is_enacted = i < game.enacted_fascist
        is_in_hitler_territory = (i >= 3)

        if is_enacted:
            # Ухвалений фашистський закон
            draw.rounded_rectangle([sx, slot_y_f, sx + slot_w_f, slot_y_f + slot_h_f], radius=8, fill=(165, 30, 30), outline=(255, 215, 100), width=3)
            draw.text((sx + slot_w_f // 2, slot_y_f + 22), "▲ FASCIST ▲", fill=(255, 215, 100), font=font_card, anchor="mm")
            draw.text((sx + slot_w_f // 2, slot_y_f + 46), "FASCHISTISCH", fill=(255, 255, 255), font=font_card, anchor="mm")
            draw.text((sx + slot_w_f // 2, slot_y_f + 66), "GESETZ", fill=(255, 200, 200), font=font_card, anchor="mm")
            draw.text((sx + slot_w_f // 2, slot_y_f + 86), f"#{i+1} УХВАЛЕНО", fill=(255, 230, 100), font=font_card_sub, anchor="mm")

            # Блок виконаної дії/повноваження, що відбулася при ухваленні
            action_name = get_slot_action_name(player_count, i)
            if action_name:
                draw.rounded_rectangle([sx + 6, slot_y_f + 104, sx + slot_w_f - 6, slot_y_f + 158], radius=6, fill=(100, 18, 18), outline=(255, 220, 120), width=1)
                draw.text((sx + slot_w_f // 2, slot_y_f + 117), "• ДІЯ ЗАКОНУ •", fill=(255, 235, 140), font=get_font(9, bold=True), anchor="mm")
                draw.text((sx + slot_w_f // 2, slot_y_f + 138), action_name, fill=(255, 255, 255), font=get_font(10, bold=True), anchor="mm", align="center")
            else:
                draw.rounded_rectangle([sx + 6, slot_y_f + 110, sx + slot_w_f - 6, slot_y_f + 152], radius=6, fill=(125, 22, 22), outline=(170, 55, 55), width=1)
                draw.text((sx + slot_w_f // 2, slot_y_f + 131), "(Без дії)", fill=(230, 180, 180), font=font_card_sub, anchor="mm")
        else:
            # Порожній слот
            if is_in_hitler_territory:
                border_color = (255, 80, 80) if is_hitler_zone_active else (190, 85, 55)
                bg_color = (65, 20, 20) if is_hitler_zone_active else (38, 14, 14)
                draw.rounded_rectangle([sx, slot_y_f, sx + slot_w_f, slot_y_f + slot_h_f], radius=8, fill=bg_color, outline=border_color, width=2)
                
                badge_bg = (160, 25, 25) if is_hitler_zone_active else (80, 25, 25)
                draw.rounded_rectangle([sx + 10, slot_y_f + 10, sx + slot_w_f - 10, slot_y_f + 30], radius=4, fill=badge_bg)
                draw.text((sx + slot_w_f // 2, slot_y_f + 20), "[!] ЗОНА ГІТЛЕРА", fill=(255, 230, 180), font=get_font(10, bold=True), anchor="mm")
                
                draw.text((sx + slot_w_f // 2, slot_y_f + 48), f"Слот {i+1}", fill=(240, 160, 160), font=font_card, anchor="mm")
            else:
                draw.rounded_rectangle([sx, slot_y_f, sx + slot_w_f, slot_y_f + slot_h_f], radius=8, fill=(35, 14, 14), outline=(110, 45, 45), width=2)
                draw.text((sx + slot_w_f // 2, slot_y_f + 32), f"Слот {i+1}", fill=(180, 110, 110), font=font_card, anchor="mm")
            
            p_text = powers[i]
            if p_text:
                draw.text((sx + slot_w_f // 2, slot_y_f + 105), p_text, fill=(240, 200, 140), font=font_card_sub, anchor="mm", align="center")
            else:
                draw.text((sx + slot_w_f // 2, slot_y_f + 105), "(Немає дії)", fill=(130, 80, 80), font=font_card_sub, anchor="mm")

    # 3.3 ПРИМІТКА / СПЕЦІАЛЬНИЙ БАНЕР УНИЗУ ФАШИСТСЬКОГО ПЛАНШЕТА
    banner_y1 = slot_y_f + slot_h_f + 18
    banner_y2 = banner_y1 + 42
    if is_hitler_zone_active:
        draw.rounded_rectangle([55, banner_y1, width - 55, banner_y2], radius=7, fill=(150, 25, 25), outline=(255, 215, 100), width=2)
        draw_danger_badge(draw, 75, (banner_y1 + banner_y2) // 2, size=15, fill_color=(255, 225, 120))
        draw_danger_badge(draw, width - 75, (banner_y1 + banner_y2) // 2, size=15, fill_color=(255, 225, 120))
        draw.text(
            (width // 2, (banner_y1 + banner_y2) // 2),
            "КРИТИЧНЕ ПОПЕРЕДЖЕННЯ: ЗОНА ГІТЛЕРА АКТИВНА! Якщо Гітлера обрано Канцлером — ФАШИСТИ ПЕРЕМАГАЮТЬ!",
            fill=(255, 255, 240),
            font=font_banner,
            anchor="mm"
        )
    else:
        draw.rounded_rectangle([55, banner_y1, width - 55, banner_y2], radius=7, fill=(42, 18, 18), outline=(190, 110, 50), width=2)
        draw_danger_badge(draw, 75, (banner_y1 + banner_y2) // 2, size=14, fill_color=(245, 180, 90))
        draw_danger_badge(draw, width - 75, (banner_y1 + banner_y2) // 2, size=14, fill_color=(245, 180, 90))
        draw.text(
            (width // 2, (banner_y1 + banner_y2) // 2),
            "ПРИМІТКА: Починаючи з 3-го ухваленого закону — обрання Гітлера Канцлером принесе Фашистам перемогу!",
            fill=(250, 205, 130),
            font=font_banner,
            anchor="mm"
        )

    # 4. ЛІЧИЛЬНИК ВИБОРІВ / ТРЕКЕР КРИЗИ (ELECTION TRACKER)
    tracker_y = 585
    draw.rounded_rectangle([40, tracker_y, width - 40, tracker_y + 145], radius=10, fill=(35, 30, 25), outline=(140, 120, 80), width=2)
    draw.text((60, tracker_y + 18), "STAATSKRISE TRACKER — МАРКЕР КРИЗИ ВИБОРІВ", fill=(220, 200, 150), font=font_sub)

    tracker_start_x = 260
    tracker_spacing = 190
    circle_y = tracker_y + 68
    radius = 26

    labels = ["0 (Норма)", "1 Провал", "2 Провали", "3 ХАОС!"]

    for i in range(4):
        cx = tracker_start_x + i * tracker_spacing
        is_active = (game.election_tracker == i)

        if is_active:
            # Чіткий золотий жетон
            draw.ellipse([cx - radius, circle_y - radius, cx + radius, circle_y + radius], fill=(230, 175, 45), outline=(255, 235, 160), width=3)
            draw.text((cx, circle_y), str(i), fill=(35, 20, 5), font=get_font(18, bold=True), anchor="mm")
        else:
            # Гніздо маркера
            draw.ellipse([cx - radius, circle_y - radius, cx + radius, circle_y + radius], fill=(26, 20, 16), outline=(80, 65, 50), width=2)
            draw.text((cx, circle_y), str(i), fill=(120, 105, 90), font=get_font(16, bold=True), anchor="mm")

        # Підпис під жетоном
        draw.text(
            (cx, circle_y + radius + 16),
            labels[i],
            fill=(245, 220, 160) if is_active else (110, 95, 80),
            font=get_font(13, bold=is_active),
            anchor="mm"
        )

    # Зберігаємо у буфер пам'яті
    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return output
