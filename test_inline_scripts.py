import re, shutil, subprocess, unittest
from pathlib import Path


class TestInlineScripts(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_every_inline_script_parses(self):
        html = Path(__file__).with_name('index.html').read_text(encoding='utf-8')
        for i, body in enumerate(re.findall(r'<script>([\s\S]*?)</script>', html)):
            r = subprocess.run(['node', '-e', 'new Function(require("fs").readFileSync(0,"utf8"))'],
                               input=body.encode('utf-8'), capture_output=True)
            self.assertEqual(r.returncode, 0, f'script {i}: {r.stderr[:300].decode('utf-8', 'replace')}')


if __name__ == '__main__':
    unittest.main()
