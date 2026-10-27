import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from english_overlap import database
from english_overlap.adventure import battle_progress, character_progress


class BattleTests(unittest.TestCase):
    def test_damage_carries_to_next_enemy_and_boss_chapter_boundaries(self):
        for damage, defeated, hp, boss, rewards in [
            (0, 0, 40, False, 0), (39, 0, 1, False, 0),
            (40, 1, 40, False, 20), (45, 1, 35, False, 20),
            (160, 4, 80, True, 80), (239, 4, 1, True, 80),
            (240, 5, 40, False, 140), (485, 10, 35, False, 280),
        ]:
            with self.subTest(damage=damage):
                battle = battle_progress(damage)
                self.assertEqual((battle['defeated'], battle['hp'], battle['is_boss'], battle['reward_xp']),
                                 (defeated, hp, boss, rewards))
                self.assertEqual(battle['chapter'], defeated // 5 + 1)

    def test_character_evolves_at_level_milestones(self):
        for level, stage, next_level in [(1, 0, 3), (2, 0, 3), (3, 1, 5), (5, 2, 10), (10, 3, None), (20, 3, None)]:
            with self.subTest(level=level):
                result = character_progress(level)
                self.assertEqual((result['stage'], result['next_evolution_level']), (stage, next_level))


class AdventurePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'adventure.sqlite3'
        database.migrate_database(self.path)
        self.session = database.create_study_session('mixed', path=self.path)
        with database.connect(self.path) as conn:
            conn.execute("INSERT INTO vocab(vocab_id,english,japanese) VALUES ('quest-word','quest','冒険')")

    def answers(self, count, timestamp, rating='known'):
        with database.connect(self.path) as conn:
            for index in range(count):
                key = f'{timestamp}-{index}'
                conn.execute("""INSERT INTO study_events
                    (event_id,session_id,event_type,vocab_id,direction,rating,occurred_at_utc,idempotency_key)
                    VALUES (?,?,'vocabulary_answer','quest-word','en_to_ja',?,?,?)""",
                    (key, self.session, rating, timestamp, key))

    def test_only_correct_answers_deal_damage_and_quest_xp_is_not_an_attack(self):
        now = datetime(2026, 10, 27, 3, tzinfo=timezone.utc)
        self.answers(9, now.isoformat())
        before = database.adventure_progress(path=self.path, now=now)
        self.assertEqual((before['training_xp'], before['battle']['hp'], before['total_xp']), (18, 22, 18))
        self.answers(11, '2026-10-27T03:01:00+00:00')
        after = database.adventure_progress(path=self.path, now=now)
        self.assertEqual((after['training_xp'], after['battle']['defeated'], after['total_xp']), (60, 1, 80))
        self.assertEqual(after['today_xp'], 80)
        self.assertEqual(after['streak_days'], 1)
        self.assertEqual(after, database.adventure_progress(path=self.path, now=now))

    def test_incorrect_answers_and_their_quest_bonus_never_hurt_the_enemy(self):
        now=datetime(2026,10,27,3,tzinfo=timezone.utc)
        self.answers(10,now.isoformat(),rating='again')
        progress=database.adventure_progress(path=self.path,now=now)
        self.assertEqual((progress['training_xp'],progress['total_damage'],progress['battle']['hp']),(40,0,40))

    def test_daily_cap_tokyo_midnight_and_level_growth(self):
        self.answers(60, '2026-10-26T14:59:00+00:00')
        before = database.adventure_progress(path=self.path, now=datetime(2026, 10, 26, 14, 59, tzinfo=timezone.utc))
        self.assertEqual((before['training_xp'], before['total_xp'], before['today_xp']), (120, 180, 180))
        self.answers(60, '2026-10-26T15:00:00+00:00')
        after = database.adventure_progress(path=self.path, now=datetime(2026, 10, 26, 15, tzinfo=timezone.utc))
        self.assertEqual((after['today'], after['training_xp'], after['total_xp'], after['today_xp']),
                         ('2026-10-27', 240, 380, 200))
        self.assertEqual((after['level'], after['character']['stage'], after['battle']['bosses_defeated']), (3, 1, 1))
        self.assertEqual(after['streak_days'], 2)
        self.assertEqual(after, database.adventure_progress(path=self.path, now=datetime(2026, 10, 27, 1, tzinfo=timezone.utc)))

    def test_overlap_retries_never_award_duplicate_damage_or_xp(self):
        payload = dict(session_id=self.session, material_id='quest-material', duration_seconds=1800, completed_sentences=40,
                       idempotency_key='quest-overlap', path=self.path)
        self.assertTrue(database.record_overlap_activity(**payload))
        first = database.adventure_progress(path=self.path)
        self.assertEqual((first['training_xp'], first['battle']['defeated'], first['total_xp']), (40, 1, 60))
        self.assertFalse(database.record_overlap_activity(**payload))
        self.assertEqual(first, database.adventure_progress(path=self.path))

    def test_one_completed_sentence_means_one_damage_and_legacy_time_is_not_guessed(self):
        database.record_overlap_activity(session_id=self.session,material_id='old-material',duration_seconds=600,
                                         idempotency_key='old-overlap',path=self.path)
        old=database.adventure_progress(path=self.path)
        self.assertEqual(old['total_damage'],0)
        database.record_overlap_activity(session_id=self.session,material_id='new-material',duration_seconds=3,
                                         completed_sentences=1,idempotency_key='new-overlap',path=self.path)
        new=database.adventure_progress(path=self.path)
        self.assertEqual((new['total_damage'],new['battle']['hp'],new['completed_sentences']),(1,39,1))
        for invalid in [-1,1.5,True,10001]:
            with self.assertRaises(ValueError):
                database.record_overlap_activity(session_id=self.session,material_id='new-material',duration_seconds=3,
                    completed_sentences=invalid,idempotency_key='bad',path=self.path)


if __name__ == '__main__':
    unittest.main()
