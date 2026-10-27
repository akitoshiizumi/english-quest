import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timezone

from english_overlap.pages import read_static_asset, render_practice_page
from english_overlap.storage import (load_saved_audio, remove_material_artifacts,
                                     save_audio_artifact, unimported_material_files,
                                     _jst_filename_timestamp)


class StorageAndPageTests(unittest.TestCase):
    def test_test_data_mode_requires_an_explicit_isolated_directory(self):
        from english_overlap.storage import ROOT, practice_data_dir
        with patch.dict('os.environ', {'ENGLISH_OVERLAP_DATA_ROLE':'test'}, clear=False):
            with patch.dict('os.environ', {'ENGLISH_OVERLAP_TEST_DATA_DIR':''}, clear=False):
                with self.assertRaisesRegex(RuntimeError, 'ENGLISH_OVERLAP_TEST_DATA_DIR'):
                    practice_data_dir()
            with tempfile.TemporaryDirectory() as temp:
                with patch.dict('os.environ', {'ENGLISH_OVERLAP_TEST_DATA_DIR':temp}, clear=False):
                    self.assertEqual(practice_data_dir(),Path(temp).resolve())
                    self.assertNotEqual(practice_data_dir(),ROOT/'practice_data')

    def test_audio_generation_writes_only_binary_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            audio_name=save_audio_artifact(b"synthetic audio",directory=folder)
            self.assertEqual((folder / audio_name).read_bytes(), b"synthetic audio")
            self.assertEqual(load_saved_audio(folder, audio_name), (b"synthetic audio", 'audio/mpeg'))
            self.assertEqual(list(folder.glob('*.json')),[])

    def test_generated_audio_filename_timestamp_uses_jst_instead_of_utc(self):
        instant=datetime(2026,10,25,2,0,0,tzinfo=timezone.utc)
        self.assertEqual(_jst_filename_timestamp(instant),'20261025_110000')
        with tempfile.TemporaryDirectory() as temp:
            filename=save_audio_artifact(b'audio',directory=temp)
            self.assertRegex(filename,r'^english_overlap_\d{8}_\d{6}_[0-9a-f]{6}\.mp3$')

    def test_legacy_material_scan_reads_only_unimported_json_files(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            source=folder/'english_overlap_news.json';source.write_text('{"text":"A news article."}',encoding='utf-8')
            (folder/'english_overlap_bad.json').write_text('{broken',encoding='utf-8')
            (folder/'english_overlap_audio.mp3').write_bytes(b'audio')
            items,errors=unimported_material_files(folder,set())
            self.assertEqual([item['file'] for item in items],['english_overlap_news.json'])
            self.assertEqual(len(items[0]['sha256']),64)
            self.assertEqual(errors[0]['file'],'english_overlap_bad.json')
            repeated,errors=unimported_material_files(folder,{'english_overlap_news.json'})
            self.assertEqual(repeated,[])
            self.assertEqual(len(errors),1)

    def test_material_artifact_removal_only_deletes_known_files_inside_storage(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audio=root/'english_overlap_material.mp3';subtitle=root/'english_overlap_material.json';other=root/'notes.txt'
            audio.write_bytes(b'audio');subtitle.write_text('{}',encoding='utf-8');other.write_text('keep',encoding='utf-8')
            result=remove_material_artifacts([audio.name,subtitle.name,'../outside.mp3',other.name],directory=root)
            self.assertEqual(result['removed'],[audio.name])
            self.assertEqual(result['skipped'],[subtitle.name,'../outside.mp3',other.name])
            self.assertEqual(result['errors'],[])
            self.assertFalse(audio.exists());self.assertTrue(subtitle.exists());self.assertTrue(other.exists())

    def test_saved_file_access_rejects_traversal_and_unknown_types(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            with self.assertRaises(ValueError):
                load_saved_audio(folder, '../english_overlap_secret.mp3')
            with self.assertRaises(ValueError):
                load_saved_audio(folder, 'english_overlap_wrong.exe')

    def test_practice_page_serves_react_build_and_hashed_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = root / 'english_overlap' / 'static' / 'app'
            (build / 'assets').mkdir(parents=True)
            (build / 'index.html').write_text('<script type="module" src="/static/app/assets/main.js"></script>', encoding='utf-8')
            (build / 'assets' / 'main.js').write_text('React app fixture', encoding='utf-8')
            self.assertIn('/static/app/assets/main.js', render_practice_page(root, 1234))
            self.assertEqual(read_static_asset('app/assets/main.js', root=root / 'english_overlap' / 'static'), (b'React app fixture', 'text/javascript'))

    def test_static_asset_is_whitelisted(self):
        asset = read_static_asset('shortcuts.js')
        self.assertEqual(asset[1], 'text/javascript; charset=utf-8')
        self.assertIn(b'EnglishOverlapKeys', asset[0])
        distribution = read_static_asset('statistics_distribution.js')
        self.assertEqual(distribution[1], 'text/javascript; charset=utf-8')
        self.assertIn(b'buildVocabularyDistribution', distribution[0])
        self.assertIsNone(read_static_asset('../database.py'))
        self.assertIsNone(read_static_asset('app/../../pages.py'))


if __name__ == '__main__':
    unittest.main()
