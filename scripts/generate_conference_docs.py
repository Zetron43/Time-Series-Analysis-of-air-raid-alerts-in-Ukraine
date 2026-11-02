import os
from pathlib import Path
import docx
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Sets internal padding for a table cell."""
    tcPr = cell._element.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def set_table_borders(table):
    """Adds thin clean black borders to a table."""
    tblPr = table._element.xpath('w:tblPr')
    if tblPr:
        borders = parse_xml(
            f'<w:tblBorders {nsdecls("w")}>\n'
            f'  <w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>\n'
            f'  <w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>\n'
            f'  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>\n'
            f'  <w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>\n'
            f'  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>\n'
            f'  <w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>\n'
            f'</w:tblBorders>'
        )
        tblPr[0].append(borders)

def create_theses_document(output_path: str):
    doc = docx.Document()
    
    # Page setup: A4, 2.3 cm margins all sides
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.3)
    section.bottom_margin = Cm(2.3)
    section.left_margin = Cm(2.3)
    section.right_margin = Cm(2.3)
    
    # Configure default Normal style
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(11)
    font.color.rgb = RGBColor(0, 0, 0)
    
    # 1. UDC (left-aligned, no indent, top line)
    p_udc = doc.add_paragraph()
    p_udc.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_udc.paragraph_format.first_line_indent = Cm(0)
    p_udc.paragraph_format.line_spacing = 1.0
    p_udc.paragraph_format.space_after = Pt(0)
    p_udc.paragraph_format.space_before = Pt(0)
    r_udc = p_udc.add_run('УДК 004.89:004.9:519.87')
    r_udc.bold = True
    
    # 2. Author (next line, right-aligned, uppercase, no degree/title)
    p_author = doc.add_paragraph()
    p_author.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_author.paragraph_format.first_line_indent = Cm(0)
    p_author.paragraph_format.line_spacing = 1.0
    p_author.paragraph_format.space_after = Pt(0)
    p_author.paragraph_format.space_before = Pt(0)
    r_author = p_author.add_run('МАРТИНЧУК Ю. А.')
    r_author.bold = True
    
    # 3. Organization (next line, right-aligned, (Країна))
    p_org = doc.add_paragraph()
    p_org.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p_org.paragraph_format.first_line_indent = Cm(0)
    p_org.paragraph_format.line_spacing = 1.0
    p_org.paragraph_format.space_after = Pt(0)
    p_org.paragraph_format.space_before = Pt(0)
    p_org.add_run('Чернівецький національний університет імені Юрія Федьковича (Україна)')
    
    # Empty line before title
    p_empty1 = doc.add_paragraph()
    p_empty1.paragraph_format.line_spacing = 1.0
    p_empty1.paragraph_format.space_after = Pt(0)
    p_empty1.paragraph_format.space_before = Pt(0)
    p_empty1.paragraph_format.first_line_indent = Cm(0)
    
    # 4. Title (center-aligned, uppercase, bold)
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title.paragraph_format.first_line_indent = Cm(0)
    p_title.paragraph_format.line_spacing = 1.0
    p_title.paragraph_format.space_after = Pt(0)
    p_title.paragraph_format.space_before = Pt(0)
    r_title = p_title.add_run('МУЛЬТИДЖЕРЕЛЬНЕ ЗЛИТТЯ ДАНИХ ТА МАШИННЕ НАВЧАННЯ ДЛЯ ОПЕРАТИВНОГО ПРОГНОЗУВАННЯ ПОВІТРЯНИХ ЗАГРОЗ НА РІВНІ РАЙОНІВ')
    r_title.bold = True
    
    # Empty line before abstract
    p_empty2 = doc.add_paragraph()
    p_empty2.paragraph_format.line_spacing = 1.0
    p_empty2.paragraph_format.space_after = Pt(0)
    p_empty2.paragraph_format.space_before = Pt(0)
    p_empty2.paragraph_format.first_line_indent = Cm(0)
    
    # 5. Abstract / Summary (italic, small letters, 2-8 lines, justify, indent 0.9 cm)
    p_abs = doc.add_paragraph()
    p_abs.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p_abs.paragraph_format.first_line_indent = Cm(0.9)
    p_abs.paragraph_format.line_spacing = 1.0
    p_abs.paragraph_format.space_after = Pt(0)
    p_abs.paragraph_format.space_before = Pt(0)
    r_abs = p_abs.add_run(
        'Досліджено проблему оперативного моніторингу та короткострокового ймовірнісного прогнозування повітряних загроз в умовах просторово-часової невизначеності. '
        'Запропоновано концепцію декомпозиції системи сповіщення до рівня 137 суверенних адміністративних районів України з моделюванням графа їх просторової суміжності. '
        'Розроблено методику мультимодального злиття гетерогенних даних (alerts.in.ua, радарів Neptun та Dimap, каналів Повітряних Сил ЗСУ) без часового витоку інформації. '
        'Впроваджено алгоритм двошарової верифікації БпЛА (підтверджені радарами vs ймовірні/дорозвідка) та модель часових рядів на базі градієнтного бустингу (LightGBM) '
        'із дискретизацією 15 хвилин, що забезпечує раннє превентивне оповіщення населення.'
    )
    r_abs.italic = True
    
    # Empty line before text
    p_empty3 = doc.add_paragraph()
    p_empty3.paragraph_format.line_spacing = 1.0
    p_empty3.paragraph_format.space_after = Pt(0)
    p_empty3.paragraph_format.space_before = Pt(0)
    p_empty3.paragraph_format.first_line_indent = Cm(0)
    
    def add_body_paragraph(text, bold_prefix="", indent=0.9):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.first_line_indent = Cm(indent)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        if bold_prefix:
            r_b = p.add_run(bold_prefix)
            r_b.bold = True
        p.add_run(text)
        return p

    # 6. Main Text
    add_body_paragraph(
        'В умовах систематичних масованих комбінованих повітряних ударів по території України критичного значення набуває своєчасне, локалізоване та достовірне оповіщення населення. '
        'Існуюча загальнодержавна система цивільного захисту функціонує переважно на рівні обласних центрів або цілих областей. '
        'Оголошення повітряної тривоги на всю територію області у разі локальної фіксації баражуючого боєприпасу в одному прикордонному районі призводить до паралічу економічної активності, '
        'зупинки освітнього процесу та зниження пильності громадян через так звану «тривожну втому» (alarm fatigue). '
        'Виникає гостра науково-прикладна суперечність між потребою у максимально ранньому виявленні цілей і необхідністю високої просторової точності локалізації тривог.',
        bold_prefix='Постановка проблеми. '
    )
    
    add_body_paragraph(
        'Для подолання вказаної проблеми сформульовано такі науково-технічні завдання: '
        '1) розробити архітектуру декомпозиції території України на рівень автономних районів на основі топологічного графа суміжності; '
        '2) створити механізм динамічного злиття даних (Data Fusion) з офіційних зведень alerts.in.ua, радіолокаційних радарів Neptun, Dimap та OSINT-джерел без витоку майбутніх значень (Zero Lookahead Bias); '
        '3) побудувати алгоритм двошарової класифікації безпілотних літальних апаратів (БпЛА) на верифіковані радіолокацією та ймовірні/розрахункові з екстраполяцією векторів підльоту; '
        '4) навчити ансамблеву предиктивну модель машинного навчання (LightGBM) для прогнозування стану тривоги на часовій сітці 15 хв – 2 год.',
        bold_prefix='Вирішувані завдання. '
    )

    add_body_paragraph(
        'Основою запропонованого методу є представлення адміністративно-територіального устрою України графом суміжності G = (V, E), '
        'де |V| = 137 вершин відповідають районам, а ребра E фіксують наявність спільного географічного кордону. '
        'Області розглядаються суто як навігаційні контейнери, тоді як кожен район наділений незалежним оперативним станом: '
        'S_i(t) ∈ {CLEAR, YELLOW, RED, NOMINAL}, i ∈ V. '
        'Це дозволяє реалізувати систему превентивного виявлення загрози: якщо в суміжних районах N(i) = {j ∈ V | (i,j) ∈ E} '
        'оголошено тривогу, користувач у районі i отримує попередження раннього реагування за 10–25 хвилин до підльоту загрози.',
        bold_prefix='Методологія та виклад дослідження. '
    )

    add_body_paragraph(
        'Інтеграція даних здійснюється через каузальне об’єднання в точці часу t_k (Point-in-Time Causal Join). '
        'Для виключення витоку інформації генерація ознак (часові синусоїдальні перетворення доби й тижня, авторегресійні лаги тривог за 15 хв, 1 год, 3 год та ковзні середні за 7 діб) '
        'виконується строго за закритим зліва інтервалом [t_k - Δt, t_k). '
        'Радіолокаційні дані Neptun і Dimap зіставляються з офіційними статусами alerts.in.ua за допомогою коефіцієнта Жаккара:'
    )

    # Formula (centered, italic for latin, no indent)
    p_form = doc.add_paragraph()
    p_form.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_form.paragraph_format.first_line_indent = Cm(0)
    p_form.paragraph_format.line_spacing = 1.0
    p_form.paragraph_format.space_before = Pt(2)
    p_form.paragraph_format.space_after = Pt(2)
    r_f1 = p_form.add_run('J(A, B) = |A ∩ B| / |A ∪ B|,')
    r_f1.italic = True
    r_fn = p_form.add_run('                                                                     (1)')
    r_fn.italic = False

    add_body_paragraph(
        'де A — множина районів з офіційною тривогою за alerts.in.ua, B — множина районів активності за радарами. '
        'Експериментальний аналіз показав J(alerts, Neptun) = 79.2% та J(alerts, Dimap) = 62.0%, що свідчить про високу узгодженість і взаємодоповнюваність джерел. '
        'Для класифікації повітряних цілей запропоновано вирішальне правило: ціль вважається підтвердженою (CONFIRMED), '
        'якщо якість позиціонування підтверджена радаром (positionQuality = "confirmed" або lifecycle = "confirmed"), '
        'або рівень довіри є високим (confidenceLevel = "high") за наявності не менше 2 джерел спостереження без екстрапольованого курсу. '
        'Усі інші контакти класифікуються як ймовірні (PROBABLE, дорозвідка/акустичні засічки) із відображенням розрахункового вектора підльоту зі швидкістю ~180 км/год.'
    )

    # Table introduction and Table
    p_tbl_title = doc.add_paragraph()
    p_tbl_title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_tbl_title.paragraph_format.first_line_indent = Cm(0.9)
    p_tbl_title.paragraph_format.line_spacing = 1.0
    p_tbl_title.paragraph_format.space_after = Pt(2)
    p_tbl_title.paragraph_format.space_before = Pt(4)
    r_tt = p_tbl_title.add_run('Таблиця 1. Порівняння моделей прогнозування повітряної тривоги на горизонті 15 хв')
    r_tt.italic = True

    table = doc.add_table(rows=4, cols=6)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    col_widths = [Cm(3.2), Cm(2.4), Cm(2.6), Cm(2.6), Cm(2.7), Cm(2.7)]
    headers = ['Регіон', 'Модель', 'PR-AUC', 'Brier Score', 'Precision (%)', 'Recall (%)']
    
    hdr_cells = table.rows[0].cells
    for i, title in enumerate(headers):
        hdr_cells[i].width = col_widths[i]
        hdr_cells[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_margins(hdr_cells[i], top=80, bottom=80, left=100, right=100)
        p = hdr_cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run(title)
        r.bold = True
        r.font.size = Pt(9.5)

    data_rows = [
        ['м. Київ', 'Baseline (наївна)', '0.3551', '0.0642', '56.6', '56.6'],
        ['м. Київ', 'LightGBM (ML)', '0.4831', '0.0692', '60.5', '51.1'],
        ['Харківська обл.', 'LightGBM (ML)', '0.9637', '0.0609', '93.4', '99.9'],
    ]

    for row_idx, data_row in enumerate(data_rows, start=1):
        row_cells = table.rows[row_idx].cells
        for col_idx, val in enumerate(data_row):
            row_cells[col_idx].width = col_widths[col_idx]
            row_cells[col_idx].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_margins(row_cells[col_idx], top=60, bottom=60, left=100, right=100)
            p = row_cells[col_idx].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT if col_idx < 2 else WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.line_spacing = 1.0
            r = p.add_run(val)
            r.font.size = Pt(9.5)
            if 'LightGBM' in data_row[1] and col_idx == 2:
                r.bold = True

    set_table_borders(table)

    # Empty space after table
    p_after_tbl = doc.add_paragraph()
    p_after_tbl.paragraph_format.line_spacing = 1.0
    p_after_tbl.paragraph_format.space_after = Pt(2)
    p_after_tbl.paragraph_format.space_before = Pt(0)
    p_after_tbl.paragraph_format.first_line_indent = Cm(0)

    add_body_paragraph(
        'Отримані результати підтверджують статистичну перевагу моделі градієнтного бустингу LightGBM (табл. 1). '
        'Для м. Києва, де спостерігається значний дисбаланс класів (переважний рівень спокою), метрика PR-AUC зросла з 0.3551 до 0.4831 (+36.0% відносно бейслайну), '
        'а точність (Precision) досягла 60.5%. Для прифронтових областей (Харківська) модель демонструє надійну дискримінацію з PR-AUC 0.9637 та повнотою 99.9%. '
        'Архітектура впроваджена у вигляді інтерактивного Telegram-бота з підтримкою інтелектуального ШІ-агента (LLM tool-calling) '
        'та автоматичною генерацією тактичних візуальних карт із векторними прогнозами підльоту загроз на горизонти 15 хв, 30 хв, 1 год і 2 год.'
    )

    add_body_paragraph(
        '1. Запропоновано і реалізовано нову парадигму по-районного суверенного моніторингу повітряної обстановки (137 районів), '
        'яка усуває хибні спрацьовування в масштабах цілої області та запобігає виникненню синдрому тривожної втоми. '
        '2. Впроваджено багатоджерельну фільтрацію та двошарову класифікацію БпЛА (підтверджені радарами vs ймовірні/дорозвідка), '
        'що дозволило поєднати юридичний факт тривоги (alerts.in.ua) із реальною кінематикою цілей (Neptun, Dimap, OSINT). '
        '3. Модель машинного навчання на основі градієнтного бустингу довела ефективність короткострокового прогнозування часових рядів повітряних тривог, '
        'перевершивши інерційний бейслайн на 36% за метрикою PR-AUC у складних умовах незбалансованого датасету.',
        bold_prefix='Висновки. '
    )

    # Empty line before Literature
    p_empty_lit = doc.add_paragraph()
    p_empty_lit.paragraph_format.line_spacing = 1.0
    p_empty_lit.paragraph_format.space_after = Pt(0)
    p_empty_lit.paragraph_format.space_before = Pt(4)
    p_empty_lit.paragraph_format.first_line_indent = Cm(0)

    # Literature header (center, bold)
    p_lit_hdr = doc.add_paragraph()
    p_lit_hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_lit_hdr.paragraph_format.first_line_indent = Cm(0)
    p_lit_hdr.paragraph_format.line_spacing = 1.0
    p_lit_hdr.paragraph_format.space_after = Pt(2)
    p_lit_hdr.paragraph_format.space_before = Pt(0)
    r_lh = p_lit_hdr.add_run('ПЕРЕЛІК ЛІТЕРАТУРИ')
    r_lh.bold = True

    literature_items = [
        '1. Ke G., Meng Q., Finley T., et al. LightGBM: A highly efficient gradient boosting decision tree. Advances in Neural Information Processing Systems. 2017. Vol. 30. P. 3146–3154.',
        '2. Saito T., Rehmsmeier M. The precision-recall plot is more informative than the ROC plot when evaluating imbalanced datasets. PLOS ONE. 2015. Vol. 10, No. 3. e0118432. DOI: 10.1371/journal.pone.0118432.',
        '3. Hall D. L., Llinas J. An introduction to multisensor data fusion. Proceedings of the IEEE. 1997. Vol. 85, No. 1. P. 6–23. DOI: 10.1109/5.554205.',
        '4. Мапа тривог України alerts.in.ua: офіційний API та оперативні зведення цивільного захисту. URL: https://alerts.in.ua (дата звернення: 02.11.2026).'
    ]

    for lit in literature_items:
        p_l = doc.add_paragraph()
        p_l.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p_l.paragraph_format.first_line_indent = Cm(0.9)
        p_l.paragraph_format.line_spacing = 1.0
        p_l.paragraph_format.space_after = Pt(0)
        p_l.paragraph_format.space_before = Pt(0)
        r_l = p_l.add_run(lit)
        r_l.font.size = Pt(10)

    doc.save(output_path)
    print(f"Successfully generated theses: {output_path}")

def create_application_document(output_path: str):
    doc = docx.Document()
    
    # Page setup: A4, 2.3 cm margins all sides
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.3)
    section.bottom_margin = Cm(2.3)
    section.left_margin = Cm(2.3)
    section.right_margin = Cm(2.3)
    
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Times New Roman'
    font.size = Pt(11)
    
    # Title
    p_hdr = doc.add_paragraph()
    p_hdr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_hdr.paragraph_format.line_spacing = 1.15
    p_hdr.paragraph_format.space_after = Pt(6)
    r_h1 = p_hdr.add_run('ЗАЯВКА УЧАСНИКА\n')
    r_h1.bold = True
    r_h1.font.size = Pt(12)
    r_h2 = p_hdr.add_run('XV Міжнародної науково-практичної конференції\n«Проблеми інформатики та комп’ютерної техніки» (ПІКТ–2026)\n(Чернівці, 12–15 листопада 2026 року)')
    r_h2.italic = True
    r_h2.font.size = Pt(10.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(0)

    # Table
    table = doc.add_table(rows=8, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    col_widths = [Cm(5.8), Cm(10.6)]
    
    fields = [
        ('Прізвище, ім’я, по-батькові', 'Мартинчук Юрій Анатолійович\n(вказати точне по-батькові за потреби)'),
        ('Науковий ступінь, вчене звання', '— (студент / дослідник)'),
        ('Посада, організація', 'Студент, Чернівецький національний університет імені Юрія Федьковича (навчально-науковий інститут фізико-технічних та комп’ютерних наук)'),
        ('Контактний тел., E-mail', 'E-mail: uramartyncuk4@gmail.com\nТел.: [вказати мобільний номер]'),
        ('Назва доповіді', 'МУЛЬТИДЖЕРЕЛЬНЕ ЗЛИТТЯ ДАНИХ ТА МАШИННЕ НАВЧАННЯ ДЛЯ ОПЕРАТИВНОГО ПРОГНОЗУВАННЯ ПОВІТРЯНИХ ЗАГРОЗ НА РІВНІ РАЙОНІВ'),
        ('Пленарна або номер секції', 'Секція 7. Самоорганізовані системи та інтелектуальний аналіз даних\n(або Секція 6. Прогресивні інформаційні технології та їх застосування)'),
        ('Потреба в готелі та форма участі в роботі конференції', 'Потреба в готелі: не потрібен.\nФорма участі: заочна (із публікацією праць у цифровій формі) / дистанційна (Google Meet).'),
        ('Співавтори / Науковий керівник (за наявності)', '[ПІБ наукового керівника, вчене звання, ступінь, посада — заповнити за наявності]')
    ]

    for idx, (label, val) in enumerate(fields):
        row_cells = table.rows[idx].cells
        row_cells[0].width = col_widths[0]
        row_cells[1].width = col_widths[1]
        set_cell_margins(row_cells[0], top=100, bottom=100, left=120, right=120)
        set_cell_margins(row_cells[1], top=100, bottom=100, left=120, right=120)
        
        p0 = row_cells[0].paragraphs[0]
        p0.paragraph_format.line_spacing = 1.05
        p0.paragraph_format.first_line_indent = Cm(0)
        p0.paragraph_format.space_after = Pt(0)
        r0 = p0.add_run(label)
        r0.bold = True
        r0.font.size = Pt(10.5)

        p1 = row_cells[1].paragraphs[0]
        p1.paragraph_format.line_spacing = 1.05
        p1.paragraph_format.first_line_indent = Cm(0)
        p1.paragraph_format.space_after = Pt(0)
        r1 = p1.add_run(val)
        r1.font.size = Pt(10.5)

    set_table_borders(table)

    p_note = doc.add_paragraph()
    p_note.paragraph_format.line_spacing = 1.15
    p_note.paragraph_format.space_before = Pt(12)
    p_note.paragraph_format.first_line_indent = Cm(0)
    r_n = p_note.add_run('Дата заповнення: 02.11.2026 р.                                             Підпис: ______________')
    r_n.italic = True
    r_n.font.size = Pt(10.5)

    doc.save(output_path)
    print(f"Successfully generated application: {output_path}")

if __name__ == '__main__':
    out_dir = Path(__file__).resolve().parent / "conference_submission_PIKT2026"
    out_dir.mkdir(parents=True, exist_ok=True)
    create_theses_document(str(out_dir / "Мартинчук_Тези.docx"))
    create_application_document(str(out_dir / "Мартинчук_Заявка.docx"))
