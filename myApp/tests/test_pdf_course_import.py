"""Faithful PDF import: verbatim split, quizzes, image blocks, no AI rewrite."""
from types import SimpleNamespace
from unittest import mock
from unittest import TestCase

from myApp.utils.lesson_blocks import prepare_lesson_article
from myApp.utils.pdf_course_import import (
    build_lesson_blocks,
    lines_to_blocks,
    parse_course_text,
    parse_extracted,
    parse_quiz_questions,
    persist_imported_course,
)


def create_editorjs_content(content_sections):
    blocks = []
    for section in content_sections:
        if section.get('type') == 'paragraph':
            blocks.append({'type': 'paragraph', 'data': {'text': section.get('text', '')}})
        elif section.get('type') == 'header':
            blocks.append({'type': 'header', 'data': {'text': section.get('text', ''), 'level': section.get('level', 2)}})
        elif section.get('type') == 'list':
            blocks.append({'type': 'list', 'data': {'style': section.get('style', 'unordered'), 'items': section.get('items', [])}})
        elif section.get('type') == 'quote':
            blocks.append({'type': 'quote', 'data': {'text': section.get('text', ''), 'caption': section.get('caption', '')}})
        elif section.get('type') == 'image':
            url = section.get('url') or ''
            if url:
                blocks.append({'type': 'image', 'data': {'file': {'url': url}, 'caption': section.get('caption', '')}})
    return {'blocks': blocks}


LIQUID_GYM_SAMPLE = """
AQUATIC THERAPY INSTITUTE (ATI) COURSE MANUAL
TABLE OF CONTENTS
CHAPTER 1
INTRODUCTION
1.1 THE ROLE OF AQUATIC THERAPY IN MODERN REHABILITATION
CHAPTER 2
INTRODUCTION
2.1 SAFETY CONSIDERATIONS
________________

INTRODUCTION - CHAPTER 1
Aquatic therapy provides clinicians with a unique rehabilitation environment that supports early mobility.
Learning Objectives
After completing this chapter, you will be able to:
1. Describe the key physical properties of water and their therapeutic relevance.
2. Name the five major hydrodynamic principles used in aquatic therapy.

1.1 THE ROLE OF AQUATIC THERAPY IN MODERN REHAB
Aquatic therapy or hydrotherapy uses the physical properties of water to provide evidence-based treatment.
* It can be used independently or in combination with traditional land-based therapy.
Aquatic_Therapy_Pillars.mp4

1.2 THE PROPERTIES OF WATER
Density:
The mass per unit volume of a substance.

1.3 HYDRODYNAMICS & THERAPEUTIC APPLICATIONS
The clinician must understand the mechanical and physiological effects.

1.3.1 BUOYANCY
Buoyancy is the upward force that counteracts gravity.
* ASIS depth: patients bear approximately 50% of their bodyweight

CHAPTER 1 SUMMARY
This chapter provided the clinical foundation needed to safely prescribe aquatic therapy.

CHAPTER 1 QUIZ
Question 1
Why are uncontrolled cardiac conditions an absolute contraindication for aquatic therapy?
Select one correct answer
A. Water decreases venous return
B. Hydrostatic pressure increases cardiac workload
C. Water eliminates cardiac load
D. Water temperature lowers blood pressure too quickly
Correct Answer: B
Question 2
Which of the following is an example of a relative precaution rather than an absolute contraindication?
Select one correct answer
A. Active infection
B. Uncontrolled epilepsy
C. Multiple sclerosis
D. Open wound
Correct Answer: C

INTRODUCTION - CHAPTER 2
Safety is the first responsibility of the aquatic therapist.

2.1 SAFETY CONSIDERATIONS
Each facility will have its own emergency and evacuation procedures.

2.4.1 STEP ENTRY TECHNIQUE
CHAPTER 2.4.1 STEP ENTRY TECHNIQUE
Step entry is most commonly used to enter and exit the pool.

CHAPTER 2 QUIZ
Question 1
Why are entry and exit considered the highest-risk parts of hydrotherapy sessions?
Select one correct answer
A. Patients are not warmed up yet
B. Water temperature changes rapidly
C. Slips, falls, and transfer errors are more likely
D. Buoyancy prevents movement
Correct Answer: C
"""


class PdfCourseParseTests(TestCase):
    def test_chapters_become_modules_and_xy_become_lessons(self):
        parsed = parse_course_text(LIQUID_GYM_SAMPLE)
        module_names = [m['name'] for m in parsed['modules']]
        self.assertEqual(len(parsed['modules']), 2)
        self.assertTrue(module_names[0].startswith('Chapter 1'))
        self.assertTrue(module_names[1].startswith('Chapter 2'))

        ch1_titles = [lesson['title'] for lesson in parsed['modules'][0]['lessons']]
        self.assertIn('Introduction', ch1_titles)
        self.assertTrue(any(t.startswith('1.1 ') for t in ch1_titles))
        self.assertTrue(any(t.startswith('1.2 ') for t in ch1_titles))
        self.assertTrue(any(t.startswith('1.3 ') for t in ch1_titles))
        self.assertTrue(any(t.startswith('1.3.1 ') for t in ch1_titles))
        self.assertTrue(any('Quiz' in t for t in ch1_titles))
        self.assertTrue(any('Summary' in t for t in ch1_titles))

    def test_nested_section_becomes_standalone_lesson(self):
        parsed = parse_course_text(LIQUID_GYM_SAMPLE)
        ch1_lessons = parsed['modules'][0]['lessons']
        nested = next(lesson for lesson in ch1_lessons if lesson['title'].startswith('1.3.1 '))
        self.assertIn('BUOYANCY', nested['title'].upper())
        self.assertEqual(nested.get('section_key'), '1.3.1')
        self.assertEqual(nested.get('nest_depth'), 2)
        self.assertEqual(nested.get('kind'), 'subsection')
        texts = [b.get('text', '') for b in nested['blocks'] if b['type'] == 'paragraph']
        self.assertTrue(
            any('Buoyancy is the upward force that counteracts gravity.' in t for t in texts)
        )
        # Parent 1.3 overview remains its own lesson without swallowing 1.3.1 body
        parent = next(lesson for lesson in ch1_lessons if lesson['title'].startswith('1.3 '))
        self.assertEqual(parent.get('section_key'), '1.3')
        self.assertEqual(parent.get('nest_depth'), 1)
        parent_paras = [b.get('text', '') for b in parent['blocks'] if b['type'] == 'paragraph']
        self.assertTrue(
            any('mechanical and physiological effects' in t for t in parent_paras)
        )
        self.assertFalse(
            any('Buoyancy is the upward force that counteracts gravity.' in t for t in parent_paras)
        )
        # Parent sorts before its sub-lesson
        titles = [lesson['title'] for lesson in ch1_lessons]
        self.assertLess(titles.index(parent['title']), titles.index(nested['title']))

    def test_nested_before_parent_heading_still_builds_hierarchy(self):
        """If the PDF lists 2.4.1 before a proper 2.4 heading, keep parent + child."""
        parsed = parse_extracted({
            'lines': [
                {'text': 'CHAPTER 2 — SAFETY', 'page': 0, 'y0': 80, 'size': 18},
                {'text': 'INTRODUCTION - CHAPTER 2', 'page': 1, 'y0': 80, 'size': 14},
                {'text': 'Overview of chapter two.', 'page': 1, 'y0': 120, 'size': 11},
                {'text': '2.4.1 STEP ENTRY TECHNIQUE', 'page': 2, 'y0': 80, 'size': 16},
                {'text': 'Step entry is common.', 'page': 2, 'y0': 140, 'size': 11},
                {'text': '2.4 ENTRY & EXIT PROCEDURES', 'page': 3, 'y0': 80, 'size': 16},
                {'text': 'Choose the safest entry method.', 'page': 3, 'y0': 140, 'size': 11},
                {'text': '2.4.2 RAMP ENTRY', 'page': 4, 'y0': 80, 'size': 16},
                {'text': 'Ramp entry for wheelchair users.', 'page': 4, 'y0': 140, 'size': 11},
                {'text': 'CHAPTER 2 SUMMARY', 'page': 5, 'y0': 80, 'size': 16},
                {'text': 'Safety first.', 'page': 5, 'y0': 140, 'size': 11},
            ],
            'images': [],
        })
        titles = [lesson['title'] for lesson in parsed['modules'][0]['lessons']]
        parent = next(t for t in titles if t.startswith('2.4 '))
        child_a = next(t for t in titles if t.startswith('2.4.1 '))
        child_b = next(t for t in titles if t.startswith('2.4.2 '))
        self.assertLess(titles.index(parent), titles.index(child_a))
        self.assertLess(titles.index(child_a), titles.index(child_b))
        self.assertIn('ENTRY', parent.upper())
        lessons = {lesson['title']: lesson for lesson in parsed['modules'][0]['lessons']}
        self.assertEqual(lessons[child_a]['nest_depth'], 2)
        self.assertEqual(lessons[parent]['nest_depth'], 1)
        self.assertFalse(lessons[parent].get('is_parent_stub'))

    def test_wording_is_verbatim(self):
        parsed = parse_course_text(LIQUID_GYM_SAMPLE)
        lesson_11 = next(
            lesson for lesson in parsed['modules'][0]['lessons'] if lesson['title'].startswith('1.1 ')
        )
        texts = [b.get('text', '') for b in lesson_11['blocks'] if b['type'] == 'paragraph']
        self.assertTrue(
            any('Aquatic therapy or hydrotherapy uses the physical properties of water' in t for t in texts)
        )
        self.assertTrue(any('Aquatic_Therapy_Pillars.mp4' in t for t in texts))
        list_items = []
        for block in lesson_11['blocks']:
            if block['type'] == 'list':
                list_items.extend(block['items'])
        self.assertIn('It can be used independently or in combination with traditional land-based therapy.', list_items)

    def test_learning_objectives_become_outcomes(self):
        parsed = parse_course_text(LIQUID_GYM_SAMPLE)
        intro = next(lesson for lesson in parsed['modules'][0]['lessons'] if lesson['kind'] == 'intro')
        self.assertEqual(len(intro['outcomes']), 2)
        self.assertTrue(intro['outcomes'][0].startswith('Describe the key physical properties'))

    def test_chapter_quiz_extracts_printed_answers(self):
        parsed = parse_course_text(LIQUID_GYM_SAMPLE)
        quiz = next(lesson for lesson in parsed['modules'][0]['lessons'] if lesson['kind'] == 'quiz')
        self.assertEqual(len(quiz['quiz_questions']), 2)
        self.assertEqual(quiz['quiz_questions'][0]['correct_answer'], 'B')
        self.assertEqual(
            quiz['quiz_questions'][0]['option_b'],
            'Hydrostatic pressure increases cardiac workload',
        )
        self.assertEqual(quiz['quiz_questions'][1]['correct_answer'], 'C')

    def test_chapter_2_4_1_heading_does_not_start_a_new_chapter(self):
        parsed = parse_course_text(LIQUID_GYM_SAMPLE)
        self.assertEqual(len(parsed['modules']), 2)
        ch2_titles = [lesson['title'] for lesson in parsed['modules'][1]['lessons']]
        self.assertTrue(any('2.1 ' in t for t in ch2_titles))
        self.assertTrue(any('2.4 ' in t or '2.4.1' in t or 'STEP ENTRY' in t.upper() for t in ch2_titles))

    def test_one_chapter_survives_title_fragments_and_temperature_range(self):
        parsed = parse_extracted({
            'lines': [
                {'text': 'INTRODUCTION - CHAPTER 2', 'page': 0, 'y0': 80, 'size': 14},
                {'text': 'CHAPTER 2 — SAFETY,', 'page': 1, 'y0': 73, 'size': 18},
                {'text': 'CHAPTER 2 SAFETY, ENVIRONMENT, RISK MANAGEMENT &', 'page': 2, 'y0': 73, 'size': 18},
                {'text': 'INTRODUCTION — CHAPTER 3', 'page': 2, 'y0': 42, 'size': 9},
                {'text': 'This chapter covers the major safety hazards in aquatic therapy.', 'page': 2, 'y0': 160, 'size': 11},
                {'text': '2.3 ENVIRONMENTAL SAFETY', 'page': 3, 'y0': 73, 'size': 16},
                {'text': '33.5 - 35.5 degrees Celsius is thermoneutral and an ideal hydrotherapy temperature.', 'page': 3, 'y0': 180, 'size': 11},
                {'text': '2.4 ENTRY & EXIT PROCEDURES', 'page': 4, 'y0': 73, 'size': 16},
                {'text': 'Step entry is most commonly used.', 'page': 4, 'y0': 160, 'size': 11},
                {'text': 'CHAPTER 2 SUMMARY', 'page': 5, 'y0': 73, 'size': 16},
                {'text': 'Safety comes first.', 'page': 5, 'y0': 160, 'size': 11},
                {'text': 'CHAPTER 2 SUMMARY', 'page': 6, 'y0': 73, 'size': 16},
                {'text': 'CHAPTER 2 QUIZ', 'page': 7, 'y0': 73, 'size': 16},
                {'text': 'Question 1', 'page': 7, 'y0': 120, 'size': 12},
                {'text': 'Why is deck safety important?', 'page': 7, 'y0': 140, 'size': 11},
                {'text': 'A. Patients walk faster', 'page': 7, 'y0': 160, 'size': 11},
                {'text': 'B. Slips and chemical exposure occur on deck', 'page': 7, 'y0': 180, 'size': 11},
                {'text': 'Correct Answer: B', 'page': 7, 'y0': 200, 'size': 11},
            ],
            'images': [],
        })
        numbers = [module['number'] for module in parsed['modules']]
        self.assertEqual(numbers, [2])
        titles = [lesson['title'] for lesson in parsed['modules'][0]['lessons']]
        self.assertEqual(titles.count('Chapter 2 Summary'), 1)
        self.assertEqual(titles.count('Chapter 2 Quiz'), 1)
        self.assertTrue(any(title.startswith('2.3 ') for title in titles))
        self.assertTrue(any(title.startswith('2.4 ') for title in titles))
        self.assertFalse(any(title.startswith('33.5') for title in titles))
        lesson_23 = next(lesson for lesson in parsed['modules'][0]['lessons'] if lesson['title'].startswith('2.3 '))
        body = ' '.join(block.get('text', '') for block in lesson_23['blocks'] if block['type'] == 'paragraph')
        self.assertIn('33.5', body)

    def test_chapter_cover_pages_do_not_become_extra_lessons(self):
        parsed = parse_extracted({
            'lines': [
                {'text': 'CHAPTER 2 — SAFETY, ENVIRONMENT, RISK MANAGEMENT', 'page': 1, 'y0': 73, 'size': 18},
                {'text': 'SAFETY, ENVIRONMENT, RISK MANAGEMENT &', 'page': 2, 'y0': 73, 'size': 18},
                {'text': 'EMERGENCY READINESS', 'page': 2, 'y0': 110, 'size': 18},
                {'text': 'INTRODUCTION — CHAPTER 3', 'page': 2, 'y0': 42, 'size': 9},
                {'text': 'CHAPTER 2 SAFETY, ENVIRONMENT, RISK MANAGEMENT &', 'page': 3, 'y0': 73, 'size': 16},
                {'text': 'Aquatic therapy involves clinical variables not present in land-based care.', 'page': 3, 'y0': 160, 'size': 11},
                {'text': 'Learning Objectives', 'page': 3, 'y0': 200, 'size': 12},
                {'text': '1. State key aquatic safety risks', 'page': 3, 'y0': 220, 'size': 11},
                {'text': '2.3 ENVIRONMENTAL SAFETY CHAPTER 2.3 ENVIRONMENTAL SAFETY', 'page': 4, 'y0': 73, 'size': 16},
                {'text': 'Pool chemistry must be checked before every session.', 'page': 4, 'y0': 160, 'size': 11},
                {'text': '2.6 EMERGENCY SCENARIOS CHAPTER 2.6 EMERGENCY SCENARIOS', 'page': 5, 'y0': 73, 'size': 16},
                {'text': 'Entry and exit are the highest-risk moments.', 'page': 5, 'y0': 160, 'size': 11},
            ],
            'images': [],
        })
        self.assertEqual([module['number'] for module in parsed['modules']], [2])
        titles = [lesson['title'] for lesson in parsed['modules'][0]['lessons']]
        self.assertEqual(titles[0], 'Introduction')
        self.assertNotIn('— SAFETY, ENVIRONMENT, RISK MANAGEMENT', titles)
        self.assertNotIn('SAFETY, ENVIRONMENT, RISK MANAGEMENT &', titles)
        self.assertTrue(any(title == '2.3 ENVIRONMENTAL SAFETY' for title in titles))
        self.assertTrue(any(title == '2.6 EMERGENCY SCENARIOS' for title in titles))
        self.assertFalse(any('CHAPTER 2.3' in title for title in titles))
        intro = parsed['modules'][0]['lessons'][0]
        texts = [block.get('text', '') for block in intro['blocks'] if block['type'] == 'paragraph']
        self.assertTrue(any('clinical variables' in text for text in texts))

    def test_quiz_parser_standalone(self):
        questions = parse_quiz_questions([
            'Question 1',
            'Why are uncontrolled cardiac conditions an absolute contraindication for aquatic therapy?',
            'Select one correct answer',
            'A. Water decreases venous return',
            'B. Hydrostatic pressure increases cardiac workload',
            'C. Water eliminates cardiac load',
            'D. Water temperature lowers blood pressure too quickly',
            'Correct Answer: B',
        ])
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]['correct_answer'], 'B')

    def test_quiz_stops_before_chapter_conclusion(self):
        questions = parse_quiz_questions([
            'Question 5',
            (
                'A patient recovering from ankle surgery presents with moderate swelling. '
                'Which hydrodynamic principle provides the MOST therapeutic benefit for edema reduction?'
            ),
            'Select one correct answer',
            '1. Buoyancy',
            '2. Viscosity',
            '3. Hydrostatic pressure',
            '4. Turbulence',
            'Correct Answer: C',
            'CONCLUSION - CHAPTER 1',
            'Key Takeaways',
            'Aquatic therapy uses the physical properties of water.',
            '1. Describe the foundational therapeutic value of aquatic therapy.',
        ])
        self.assertEqual(len(questions), 1)
        self.assertEqual(
            questions[0]['question'],
            (
                'A patient recovering from ankle surgery presents with moderate swelling. '
                'Which hydrodynamic principle provides the MOST therapeutic benefit for edema reduction?'
            ),
        )
        self.assertNotIn('CONCLUSION', questions[0]['question'])
        self.assertNotIn('Key Takeaways', questions[0]['question'])
        self.assertEqual(questions[0]['option_a'], 'Buoyancy')
        self.assertEqual(questions[0]['option_c'], 'Hydrostatic pressure')
        self.assertEqual(questions[0]['correct_answer'], 'C')

    def test_conclusion_heading_starts_its_own_lesson(self):
        parsed = parse_course_text(
            LIQUID_GYM_SAMPLE
            + '\nCONCLUSION - CHAPTER 2\nKey Takeaways\nSafety comes first.\n'
        )
        ch2 = parsed['modules'][1]['lessons']
        titles = [lesson['title'] for lesson in ch2]
        self.assertIn('Conclusion', titles)
        quiz = next(lesson for lesson in ch2 if lesson['kind'] == 'quiz')
        last_q = quiz['quiz_questions'][-1]
        self.assertNotIn('CONCLUSION', last_q['question'])
        self.assertNotIn('Key Takeaways', last_q['question'])

    def test_inline_numbered_objectives_become_a_list(self):
        blocks = lines_to_blocks([
            'Learning Objectives',
            (
                'After completing this chapter, you will be able to: '
                '1. Describe the key physical properties of water. '
                '2. Name the five major hydrodynamic principles. '
                '3. Differentiate between hydrostatic pressure and buoyancy.'
            ),
        ])
        lists = [b for b in blocks if b['type'] == 'list']
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0]['style'], 'ordered')
        self.assertEqual(len(lists[0]['items']), 3)
        self.assertTrue(lists[0]['items'][0].startswith('Describe the key physical'))
        preamble = next(b['text'] for b in blocks if b['type'] == 'paragraph')
        self.assertIn('you will be able to', preamble)

    def test_lines_to_blocks_keeps_exact_paragraph(self):
        blocks = lines_to_blocks([
            '1.2 THE PROPERTIES OF WATER',
            'Density:',
            'The mass per unit volume of a substance.',
        ])
        paragraphs = [b['text'] for b in blocks if b['type'] == 'paragraph']
        self.assertTrue(any('The mass per unit volume of a substance.' in text for text in paragraphs))

    def test_plain_text_without_chapters_still_makes_a_lesson(self):
        parsed = parse_course_text(
            "This is a paragraph from a manual without chapter headings.\n"
            "Another line of body copy that should still be imported."
        )
        self.assertEqual(len(parsed['modules']), 1)
        self.assertEqual(parsed['modules'][0]['name'], 'Imported Manual')
        self.assertEqual(len(parsed['modules'][0]['lessons']), 1)
        paragraphs = [
            b['text']
            for b in parsed['modules'][0]['lessons'][0]['blocks']
            if b['type'] == 'paragraph'
        ]
        self.assertTrue(any('without chapter headings' in text for text in paragraphs))

    def test_create_editorjs_content_supports_image_blocks(self):
        content = create_editorjs_content([
            {'type': 'paragraph', 'text': 'Hello'},
            {'type': 'image', 'url': 'https://cdn.example.com/fig.png', 'caption': 'Figure 1'},
        ])
        types = [b['type'] for b in content['blocks']]
        self.assertEqual(types, ['paragraph', 'image'])
        self.assertEqual(content['blocks'][1]['data']['file']['url'], 'https://cdn.example.com/fig.png')
        self.assertEqual(content['blocks'][1]['data']['caption'], 'Figure 1')

    def test_lesson_image_template_renders_editorjs_file_url(self):
        from django.template import Context, Engine

        # Same lookup shape as lesson.html. Must not read block.data.url when
        # only block.data.file.url exists (Django |default: raises in DEBUG).
        template = Engine(debug=True).from_string(
            '{% if block.data.file.url %}'
            '<img src="{{ block.data.file.url }}" alt="{{ block.data.caption|default:"Lesson figure" }}">'
            '{% elif block.data.url %}'
            '<img src="{{ block.data.url }}" alt="{{ block.data.caption|default:"Lesson figure" }}">'
            '{% endif %}'
        )
        html = template.render(Context({
            'block': {
                'type': 'image',
                'data': {
                    'file': {'url': 'https://cdn.example.com/fig.png'},
                    'caption': '',
                },
            },
        }))
        self.assertIn('https://cdn.example.com/fig.png', html)
        self.assertIn('Lesson figure', html)

    def test_interrupted_numbered_questions_stay_one_two_three_four(self):
        article = prepare_lesson_article({
            'blocks': [
                {'type': 'paragraph', 'data': {'text': (
                    'Proper screening allows the therapist to determine whether aquatic therapy is sa '
                    'Four core clinical screening questions:'
                )}},
                {'type': 'list', 'data': {'style': 'ordered', 'items': ['Is this patient SAFE to enter the pool?']}},
                {'type': 'paragraph', 'data': {'text': '● This includes cognitive, medical, emotional, and mobility readiness.'}},
                {'type': 'list', 'data': {'style': 'ordered', 'items': ['What level of support is required?']}},
                {'type': 'paragraph', 'data': {'text': '● Independent? Rail? Noodle? Contact guard?'}},
                {'type': 'list', 'data': {'style': 'ordered', 'items': ['What depth is appropriate?']}},
                {'type': 'paragraph', 'data': {'text': '● Depth determines load, balance demands, and pain response.'}},
                {'type': 'list', 'data': {'style': 'ordered', 'items': ['What are the initial red or yellow flags?']}},
                {'type': 'paragraph', 'data': {'text': (
                    '● Flags indicate how conservative or progressive the session must be. '
                    'If screening is done correctly, it greatly reduces adverse events in the water.'
                )}},
            ],
        })
        lists = [block for block in article['blocks'] if block['type'] == 'list']
        self.assertEqual(len(lists), 1)
        self.assertEqual(lists[0]['data']['style'], 'ordered')
        self.assertEqual(len(lists[0]['data']['items']), 4)
        self.assertTrue(lists[0]['data']['items'][0].startswith('Is this patient SAFE'))
        self.assertIn('cognitive, medical', lists[0]['data']['items'][0])
        closers = [
            block['data']['text']
            for block in article['blocks']
            if block['type'] == 'paragraph' and 'If screening is done correctly' in block['data']['text']
        ]
        self.assertEqual(len(closers), 1)
        headings = [
            block['data']['text']
            for block in article['blocks']
            if block['type'] == 'header'
        ]
        self.assertTrue(any('Four Core Clinical Screening Questions' in text or 'Four core' in text for text in headings))

    def test_prepare_article_splits_lists_and_hoists_cover(self):
        article = prepare_lesson_article({
            'blocks': [
                {'type': 'paragraph', 'data': {'text': (
                    'After completing this chapter, you will be able to: '
                    '1. Describe the key physical properties of water. '
                    '2. Name the five major hydrodynamic principles.'
                )}},
                {'type': 'image', 'data': {'file': {'url': 'https://cdn.example.com/cover.png'}, 'caption': ''}},
            ],
        })
        self.assertEqual(len(article['lead_images']), 1)
        self.assertEqual(article['lead_images'][0]['data']['file']['url'], 'https://cdn.example.com/cover.png')
        types = [b['type'] for b in article['blocks']]
        self.assertEqual(types, ['paragraph', 'list'])
        self.assertEqual(len(article['blocks'][1]['data']['items']), 2)

    def test_heading_only_lesson_keeps_following_page_images(self):
        parsed = parse_extracted({
            'lines': [
                {'text': 'INTRODUCTION - CHAPTER 1', 'page': 0, 'y0': 10, 'size': 14},
                {'text': 'Opening paragraph.', 'page': 0, 'y0': 20, 'size': 11},
                {'text': '1.5 OTHER PHYSIOLOGICAL EFFECTS OF IMMERSION', 'page': 1, 'y0': 10, 'size': 14},
                {'text': 'Warm water results in muscle relaxation.', 'page': 1, 'y0': 30, 'size': 11},
                {'text': '1.6 CASE STUDY', 'page': 2, 'y0': 10, 'size': 14},
                {'text': 'CHAPTER 1 SUMMARY', 'page': 4, 'y0': 10, 'size': 14},
                {'text': 'This chapter provided the clinical foundation.', 'page': 4, 'y0': 30, 'size': 11},
            ],
            'images': [
                {
                    'page': 3,
                    'y0': 80,
                    'bytes': b'case-a',
                    'content_type': 'image/png',
                    'caption': 'Case card 1',
                },
                {
                    'page': 3,
                    'y0': 360,
                    'bytes': b'case-b',
                    'content_type': 'image/png',
                    'caption': 'Case card 2',
                },
            ],
        })
        lessons = {lesson['title']: lesson for lesson in parsed['modules'][0]['lessons']}
        case = lessons['1.6 CASE STUDY']
        image_captions = [block.get('caption') for block in case['blocks'] if block['type'] == 'image']
        self.assertEqual(image_captions, ['Case card 1', 'Case card 2'])
        summary = lessons['Chapter 1 Summary']
        self.assertFalse(any(block['type'] == 'image' for block in summary['blocks']))

    def test_images_are_woven_between_text_by_pdf_position(self):
        blocks = build_lesson_blocks(
            [
                {'text': '1.3.1 BUOYANCY', 'page': 0, 'y0': 10},
                {'text': 'Buoyancy is the upward force that counteracts gravity.', 'page': 0, 'y0': 20},
                {'text': '1.3.2 HYDROSTATIC PRESSURE', 'page': 0, 'y0': 40},
                {'text': 'Hydrostatic pressure is the pressure exerted on immersed objects.', 'page': 0, 'y0': 50},
            ],
            [
                {'page': 0, 'y0': 25, 'bytes': b'a', 'content_type': 'image/png', 'caption': 'Fig A'},
                {'page': 0, 'y0': 55, 'bytes': b'b', 'content_type': 'image/png', 'caption': 'Fig B'},
            ],
            kind='section',
        )
        types = [block['type'] for block in blocks]
        self.assertEqual(types, ['header', 'paragraph', 'image', 'header', 'paragraph', 'image'])
        self.assertEqual(blocks[2]['caption'], 'Fig A')
        self.assertEqual(blocks[5]['caption'], 'Fig B')

    def test_stacked_images_are_spread_through_subsections(self):
        article = prepare_lesson_article({
            'blocks': [
                {'type': 'header', 'data': {'text': '1.3.1 BUOYANCY', 'level': 3}},
                {'type': 'paragraph', 'data': {'text': 'Buoyancy is the upward force.'}},
                {'type': 'header', 'data': {'text': '1.3.2 HYDROSTATIC PRESSURE', 'level': 3}},
                {'type': 'paragraph', 'data': {'text': 'Hydrostatic pressure is the pressure.'}},
                {'type': 'image', 'data': {'file': {'url': 'https://cdn.example.com/a.png'}, 'caption': ''}},
                {'type': 'image', 'data': {'file': {'url': 'https://cdn.example.com/b.png'}, 'caption': ''}},
            ],
        })
        self.assertEqual(article['lead_images'], [])
        types = [block['type'] for block in article['blocks']]
        self.assertEqual(types, ['header', 'paragraph', 'image', 'header', 'paragraph', 'image'])
        urls = [
            block['data']['file']['url']
            for block in article['blocks']
            if block['type'] == 'image'
        ]
        self.assertEqual(urls, ['https://cdn.example.com/a.png', 'https://cdn.example.com/b.png'])

    def test_google_docs_zwsp_paragraph_becomes_lists_and_headings(self):
        zwsp = '\u200b'
        blob = (
            f'After completing this chapter, you will be able to: 1.{zwsp}Describe the key physical properties of water and their therapeutic relevance. '
            f'2.{zwsp}Name the five major hydrodynamic principles used in aquatic therapy. '
            f'3.{zwsp}Understand how buoyancy, hydrostatic pressure, viscosity, drag, and turbulence affect movement and treatment planning '
            f'4.{zwsp}Describe the mechanisms by which aquatic therapy modulates pain and influences physiological function. '
            f'5.{zwsp}Apply foundational aquatic therapy principles to basic clinical decision-making. '
            f'Overview ●{zwsp}The role of aquatic therapy in rehabilitation ●{zwsp}The basic properties of water '
            f'●{zwsp}Hydrodynamics and therapeutic applications Clinical Relevance This chapter provides the clinical foundation needed to safely prescribe aquatic therapy interventions. '
            f'Study Time Estimated study time: 45 - 60 minutes '
            f'Assessment Note This chapter concludes with a case application, reflection prompt, and knowledge check.'
        )
        article = prepare_lesson_article({
            'blocks': [
                {'type': 'header', 'data': {'text': 'Learning Objectives', 'level': 3}},
                {'type': 'paragraph', 'data': {'text': blob}},
            ],
        })
        types = [b['type'] for b in article['blocks']]
        self.assertEqual(types[:4], ['header', 'paragraph', 'list', 'header'])
        self.assertEqual(article['blocks'][0]['data']['text'], 'Learning Objectives')
        self.assertIn('you will be able to', article['blocks'][1]['data']['text'])
        self.assertEqual(article['blocks'][2]['data']['style'], 'ordered')
        self.assertEqual(len(article['blocks'][2]['data']['items']), 5)
        headings = [b['data']['text'] for b in article['blocks'] if b['type'] == 'header']
        self.assertIn('Overview', headings)
        self.assertIn('Clinical Relevance', headings)
        self.assertIn('Study Time', headings)
        self.assertIn('Assessment Note', headings)
        bullets = next(b for b in article['blocks'] if b['type'] == 'list' and b['data']['style'] == 'unordered')
        self.assertGreaterEqual(len(bullets['data']['items']), 3)
        study = next(
            b['data']['text'] for b in article['blocks']
            if b['type'] == 'paragraph' and '45 - 60 minutes' in b['data']['text']
        )
        self.assertTrue(study.startswith('Estimated study time'))

    def test_definition_terms_and_glued_sentences_split(self):
        article = prepare_lesson_article({
            'blocks': [
                {'type': 'header', 'data': {'text': '1.2 THE PROPERTIES OF WATER', 'level': 2}},
                {'type': 'paragraph', 'data': {'text': (
                    'Density: The mass per unit volume of a substance. At 4 degrees Celsius, '
                    'water has a density of 1 g/mL (26) with the density of water being slightly '
                    'less at warmer temperatures.The human body’s density is less than that of water. '
                    'Specific gravity: The ratio of a body’s weight density to the weight density of water. '
                    'Thermodynamics: Heat transfer begins immediately on immersion.'
                )}},
            ],
        }, title='1.2 THE PROPERTIES OF WATER')
        headings = [b['data']['text'] for b in article['blocks'] if b['type'] == 'header']
        self.assertIn('Density', headings)
        self.assertIn('Specific gravity', headings)
        self.assertIn('Thermodynamics', headings)
        self.assertNotIn('1.2 THE PROPERTIES OF WATER', headings)
        density = next(
            b['data']['text'] for b in article['blocks']
            if b['type'] == 'paragraph' and 'mass per unit volume' in b['data']['text']
        )
        self.assertIn('. The human', density)

    def test_wrapped_section_title_joins_and_keeps_following_image(self):
        article = prepare_lesson_article(
            {
                'blocks': [
                    {'type': 'header', 'data': {'text': '3.6 DEPTH SELECTION — CLINICAL', 'level': 2}},
                    {'type': 'header', 'data': {'text': 'Reasoning', 'level': 3}},
                    {'type': 'image', 'data': {'file': {'url': 'https://cdn.example.com/depth.png'}, 'caption': ''}},
                ],
            },
            title='3.6 DEPTH SELECTION — CLINICAL REASONING',
        )
        headings = [block['data']['text'] for block in article['blocks'] if block['type'] == 'header']
        self.assertEqual(headings, [])
        self.assertEqual(len(article['lead_images']), 1)

    def test_functional_tests_split_on_import_and_display(self):
        glued = (
            'The therapist should select the most suitable assessments based on the '
            'individual patient’s condition and goals. '
            'Test 1 - 30-Second Chair Stand Test Measures functional lower body strength. '
            'See Appendix A '
            'Test 2 - 4-Stage Balance Test Measures static postural stability. '
            'Test 3 - Functional Reach Test Measures the maximum distance a person can reach.'
        )
        article = prepare_lesson_article({'blocks': [{'type': 'paragraph', 'data': {'text': glued}}]})
        headings = [block['data']['text'] for block in article['blocks'] if block['type'] == 'header']
        self.assertEqual(
            headings,
            [
                'Test 1 - 30-Second Chair Stand Test',
                'Test 2 - 4-Stage Balance Test',
                'Test 3 - Functional Reach Test',
            ],
        )
        self.assertGreaterEqual(sum(1 for block in article['blocks'] if block['type'] == 'paragraph'), 3)

        imported = lines_to_blocks([
            'The standardized functional tests listed below can be administered on land.',
            'Test 1 - 30-Second Chair Stand Test',
            'Measures functional lower body strength and endurance.',
            'Test 2 - 4-Stage Balance Test',
            'Measures static postural stability and fall risk.',
        ])
        imported_headings = [block['text'] for block in imported if block['type'] == 'header']
        self.assertEqual(
            imported_headings,
            ['Test 1 - 30-Second Chair Stand Test', 'Test 2 - 4-Stage Balance Test'],
        )

    def test_mid_lesson_headings_bullets_and_numbered_observations(self):
        zwsp = '\u200b'
        article = prepare_lesson_article({
            'blocks': [{
                'type': 'paragraph',
                'data': {'text': (
                    f'Buoyancy is the upward force that counteracts gravity. '
                    f'Depth-Based Biomechanics (4) ●{zwsp}ASIS depth: patients bear approximately 50% '
                    f'●{zwsp}Xiphoid depth: patients bear approximately 25–35% '
                    f'Physiological Effects Hydrostatic pressure effects begin immediately. '
                    f'With immersion to the neck the following changes are observed: '
                    f'1.{zwsp}Increased central blood volume by 60% '
                    f'2.{zwsp}Reduced swelling → ideal for post-surgical joints '
                    f'Precautions: ●{zwsp}Patients with hypermobility/joint laxity '
                    f'●{zwsp}Patients may require buoyancy aids'
                )},
            }],
        })
        headings = [b['data']['text'] for b in article['blocks'] if b['type'] == 'header']
        self.assertIn('Depth-Based Biomechanics (4)', headings)
        self.assertIn('Physiological Effects', headings)
        self.assertIn('Precautions', headings)
        ordered = next(b for b in article['blocks'] if b['type'] == 'list' and b['data']['style'] == 'ordered')
        self.assertEqual(len(ordered['data']['items']), 2)
        bullets = [b for b in article['blocks'] if b['type'] == 'list' and b['data']['style'] == 'unordered']
        self.assertGreaterEqual(len(bullets), 2)

    def test_wrapped_bullet_lines_stay_on_the_same_item(self):
        blocks = lines_to_blocks([
            'Pain decreases in water due to:',
            '* Reduced weight bearing due to buoyancy resulting in decreased load on joints and muscles',
            'affected - including temperature, touch, and pressure receptors (2)',
            '* Gate control stimulation via thermal and mechanical input.',
        ])
        lists = [b for b in blocks if b['type'] == 'list']
        self.assertEqual(len(lists), 1)
        self.assertEqual(len(lists[0]['items']), 2)
        self.assertIn('affected - including temperature', lists[0]['items'][0])

    def test_system_colon_rows_stay_as_bullets(self):
        zwsp = '\u200b'
        article = prepare_lesson_article({
            'blocks': [{
                'type': 'paragraph',
                'data': {'text': (
                    f'●{zwsp}Musculoskeletal system: Warm water results in muscle relaxation. '
                    f'●{zwsp}Psychological system: Hydrotherapy decreases cortisol levels. '
                    f'●{zwsp}Vascular system: Decreased vasoconstriction by 30%.'
                )},
            }],
        })
        lists = [b for b in article['blocks'] if b['type'] == 'list']
        self.assertEqual(len(lists), 1)
        self.assertEqual(len(lists[0]['data']['items']), 3)
        self.assertTrue(lists[0]['data']['items'][0].startswith('Musculoskeletal system:'))


class PdfCoursePersistTests(TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myProject.settings')
        import django
        django.setup()
        super().setUpClass()

    def _fake_course(self):
        tenant = SimpleNamespace(id=7)
        lessons_qs = mock.Mock()
        lessons_qs.filter.return_value.exists.return_value = False
        course = SimpleNamespace(
            id=11,
            tenant=tenant,
            tenant_id=7,
            name='Imported PDF Course',
            short_description='Imported from uploaded course manual.',
            description='Imported from uploaded course manual.',
            lessons=lessons_qs,
            saved_fields=None,
        )

        def save(update_fields=None):
            course.saved_fields = update_fields

        course.save = save
        return course

    def test_persist_creates_modules_lessons_and_quiz_rows(self):
        parsed = parse_course_text(LIQUID_GYM_SAMPLE)
        course = self._fake_course()
        created_lessons = []
        created_questions = []
        lesson_id = {'n': 0}

        def lesson_create(**kwargs):
            lesson_id['n'] += 1
            lesson = SimpleNamespace(id=lesson_id['n'], **kwargs)
            created_lessons.append(lesson)
            return lesson

        quiz = SimpleNamespace(id=1)
        with mock.patch('myApp.utils.iceberg.is_configured', return_value=False), \
             mock.patch('myApp.models.Module') as Module, \
             mock.patch('myApp.models.Lesson') as Lesson, \
             mock.patch('myApp.models.LessonQuiz') as LessonQuiz, \
             mock.patch('myApp.models.LessonQuizQuestion') as LessonQuizQuestion:
            Module.objects.create.side_effect = lambda **kw: SimpleNamespace(id=1, **kw)
            Lesson.objects.create.side_effect = lesson_create
            LessonQuiz.objects.get_or_create.return_value = (quiz, True)
            LessonQuizQuestion.objects.create.side_effect = lambda **kw: created_questions.append(kw)
            stats = persist_imported_course(
                course,
                parsed,
                generate_slug=lambda t: t.lower().replace(' ', '-')[:80],
                create_editorjs_content=create_editorjs_content,
            )

        self.assertEqual(stats['modules'], 2)
        self.assertGreaterEqual(stats['lessons'], 6)
        self.assertEqual(stats['questions'], 3)
        titles = [lesson.title for lesson in created_lessons]
        self.assertTrue(any(t.startswith('1.1 ') for t in titles))
        self.assertIn('Chapter 1 Quiz', titles)
        lesson_11 = next(lesson for lesson in created_lessons if lesson.title.startswith('1.1 '))
        texts = [b['data'].get('text', '') for b in lesson_11.content.get('blocks', [])]
        self.assertTrue(any('hydrotherapy uses the physical properties of water' in t for t in texts))
        self.assertEqual(created_questions[0]['correct_option'], 'B')
        self.assertEqual(created_questions[1]['correct_option'], 'C')

    def test_persist_uploads_figures_to_iceberg(self):
        parsed = parse_course_text(LIQUID_GYM_SAMPLE)
        parsed['modules'][0]['lessons'][1].setdefault('images', []).append({
            'bytes': b'\x89PNG\r\n\x1a\nfake',
            'content_type': 'image/png',
            'caption': 'Depth chart',
        })
        course = self._fake_course()
        created_lessons = []

        def lesson_create(**kwargs):
            lesson = SimpleNamespace(id=len(created_lessons) + 1, **kwargs)
            created_lessons.append(lesson)
            return lesson

        with mock.patch('myApp.utils.iceberg.is_configured', return_value=True), \
             mock.patch('myApp.utils.iceberg.upload_bytes', return_value='https://cdn.katalyst-crm.com/t1/fig.png') as upload_bytes, \
             mock.patch('myApp.models.Module') as Module, \
             mock.patch('myApp.models.Lesson') as Lesson, \
             mock.patch('myApp.models.LessonQuiz') as LessonQuiz, \
             mock.patch('myApp.models.LessonQuizQuestion') as LessonQuizQuestion:
            Module.objects.create.side_effect = lambda **kw: SimpleNamespace(id=1, **kw)
            Lesson.objects.create.side_effect = lesson_create
            LessonQuiz.objects.get_or_create.return_value = (SimpleNamespace(id=1), True)
            LessonQuizQuestion.objects.create.return_value = SimpleNamespace(id=1)
            persist_imported_course(
                course,
                parsed,
                generate_slug=lambda t: t.lower().replace(' ', '-')[:80],
                create_editorjs_content=create_editorjs_content,
            )

        upload_bytes.assert_called()
        lesson_11 = next(lesson for lesson in created_lessons if lesson.title.startswith('1.1 '))
        image_blocks = [b for b in lesson_11.content['blocks'] if b['type'] == 'image']
        self.assertEqual(image_blocks[0]['data']['file']['url'], 'https://cdn.katalyst-crm.com/t1/fig.png')

    def test_import_tab_markup_is_in_template(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / 'templates' / 'dashboard' / 'add_course.html').read_text()
        self.assertIn('Import Manual (PDF)', html)
        self.assertIn('name="import_mode"', html)
        self.assertIn('name="manual_pdf"', html)
        self.assertIn('keep the exact words', html.lower())
        self.assertIn('AI will not rewrite the copy', html)

        courses_html = (Path(__file__).resolve().parents[1] / 'templates' / 'dashboard' / 'courses.html').read_text()
        self.assertIn('dashboard_import_course_pdf', courses_html)
        self.assertIn('Import PDF', courses_html)