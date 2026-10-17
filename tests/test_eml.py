import sys
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_eml import build, EmailHTML, slug

class RendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.src = Path(self.temp.name) / 'source'
        self.dest = Path(self.temp.name) / 'site'
        self.src.mkdir()

    def put(self, name, msg):
        path = self.src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(msg.as_bytes())

    def message(self, subject, message_id, parent=None):
        m = EmailMessage()
        m['From'] = 'Alice <alice@example.com>'
        m['To'] = 'Bob <bob@example.com>'
        m['Subject'] = subject
        m['Message-ID'] = '<' + message_id + '>'
        if parent:
            m['In-Reply-To'] = '<' + parent + '>'
        m['Date'] = 'Thu, 8 Oct 2026 08:00:00 -0400'
        m.set_content('Hi Bob!\n\nOn Wednesday Bob wrote:\n> Original message')
        return m

    def test_thread_filenames_and_index(self):
        a = self.message('Important Discussion', 'one@example.com')
        b = self.message('Re: Important Discussion', 'two@example.com', 'one@example.com')
        self.put('Email One.eml', a)
        self.put('Responses/Email Two.eml', b)
        self.assertEqual(build(self.src, self.dest), 2)
        first = (self.dest / 'email-one/index.html').read_text()
        second = (self.dest / 'responses/email-two/index.html').read_text()
        self.assertIn('In this thread', first)
        self.assertIn('alice@example.com', second)
        self.assertIn('Show quoted correspondence', first)
        self.assertIn('/responses/email-two/', (self.dest / '_mail/index.html').read_text())
        self.assertFalse(list(self.dest.rglob('*.eml')))

    def test_sanitizes_remote_html_and_renders_inline_cid(self):
        msg = self.message('Picture', 'picture@example.com')
        msg.add_alternative('<h2>Hello</h2><script>alert(1)</script><img src="https://tracker.example/pixel"><img src="cid:graphic@example.com"><a href="javascript:evil()">bad</a><a href="https://example.com">safe</a>', subtype='html')
        msg.get_payload()[1].add_related(b'\x89PNG\r\n\x1a\n', maintype='image', subtype='png', cid='<graphic@example.com>', filename='picture.png')
        self.put('Picture.eml', msg)
        build(self.src, self.dest)
        page = (self.dest / 'picture/index.html').read_text()
        self.assertIn('data:image/png;base64,', page)
        self.assertNotIn('<script>', page)
        self.assertNotIn('tracker.example', page)
        self.assertNotIn('javascript:evil()', page)
        self.assertIn('https://example.com', page)
        self.assertTrue(list((self.dest / '_mail/attachments').rglob('*.bin')))

    def test_missing_parent_still_groups_sibling_replies(self):
        a = self.message('Re: Missing root', 'one@example.com', 'missing@example.com')
        b = self.message('Re: Missing root', 'two@example.com', 'missing@example.com')
        self.put('First.eml', a)
        self.put('Second.eml', b)
        build(self.src, self.dest)
        index = (self.dest / '_mail/index.html').read_text()
        self.assertIn('2 messages', index)
        self.assertEqual(index.count('<li>'), 1)

    def test_colliding_slugs_and_escape(self):
        self.put('A B.eml', self.message('<Bad> & nice', 'a@example.com'))
        self.put('A-B.eml', self.message('Other', 'b@example.com'))
        build(self.src, self.dest)
        self.assertEqual(len(list(self.dest.rglob('index.html'))), 3)
        html = (self.dest / 'a-b/index.html').read_text()
        self.assertIn('&lt;Bad&gt; &amp; nice', html)

    def test_inline_allowlist(self):
        parser = EmailHTML({})
        parser.feed('<h1 style="color:red">hi</h1><iframe src="https://other">evil</iframe><img src="https://outside">')
        rendered = ''.join(parser.output)
        self.assertIn('color:red', rendered)
        self.assertNotIn('evil', rendered)
        self.assertNotIn('outside', rendered)

if __name__ == '__main__': unittest.main()
