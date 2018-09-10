from django.conf import settings
from django.test import TestCase, override_settings

from botany import actions, models, scheduler
from core.runner import Result, ResultType

from . import factories


class CreateUserTests(TestCase):
    def test_create_user(self):
        user = actions.create_user("alice@example.com", "Alice Apple")

        self.assertEqual(user.email_addr, "alice@example.com")
        self.assertEqual(user.name, "Alice Apple")
        self.assertEqual(len(user.api_token), 12)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_admin)
        self.assertFalse(user.is_superuser)


class DeactivateUserTests(TestCase):
    def test_deactivate_user(self):
        user = factories.create_user(num_bots=2)

        actions.deactivate_user(user)

        self.assertFalse(user.is_active)
        self.assertIsNone(user.active_bot)


class CreateBotTests(TestCase):
    def test_create_bot(self):
        user = factories.create_user()
        code = factories.bot_code("randobot")

        bot = actions.create_bot(user, "randobot", code)

        self.assertEqual(bot.user, user)
        self.assertEqual(bot.name, "randobot")
        self.assertEqual(bot.code, code)
        self.assertTrue(bot.is_active)
        self.assertEqual(user.active_bot, bot)


class SetBotActiveTests(TestCase):
    def test_set_bot_active(self):
        user = factories.create_user(num_bots=2)
        bot1, bot2 = user.bots.all()
        self.assertFalse(bot1.is_active)
        self.assertTrue(bot2.is_active)

        actions.set_bot_active(bot1)

        bot1.refresh_from_db()
        bot2.refresh_from_db()

        self.assertTrue(bot1.is_active)
        self.assertFalse(bot2.is_active)


@override_settings(USE_QUEUES=True)
class ScheduleUnplayedGamesForBotTests(TestCase):
    def test_schedule_unplayed_games_for_bot(self):
        bot1, bot2 = [factories.create_bot() for _ in range(2)]
        factories.report_result(bot1.id, bot2.id, 1)
        factories.report_result(bot1.id, bot2.id, -1)
        factories.report_result(bot2.id, bot1.id, 1)

        scheduler.clear_queues()

        actions.schedule_unplayed_games_for_bot(bot1)

        expected_num_jobs_per_queue = [2, 2, 2, 1, 0]
        num_jobs_per_queue = [
            len(scheduler.get_queue_by_ix(ix).jobs)
            for ix in range(settings.BOTANY_NUM_ROUNDS)
        ]

        self.assertEqual(num_jobs_per_queue, expected_num_jobs_per_queue)


@override_settings(USE_QUEUES=True)
class ScheduleAllUnplayedGamesTests(TestCase):
    def test_schedule_unplayed_games_for_bot(self):
        bot1, bot2, bot3 = [factories.create_bot() for _ in range(3)]
        factories.report_result(bot1.id, bot2.id, 1)
        factories.report_result(bot1.id, bot2.id, -1)
        factories.report_result(bot1.id, bot3.id, 1)
        factories.report_result(bot1.id, bot3.id, -1)
        factories.report_result(bot2.id, bot1.id, 1)
        factories.report_result(bot3.id, bot1.id, 1)

        scheduler.clear_queues()

        actions.schedule_all_unplayed_games()

        expected_num_jobs_per_queue = [6, 6, 6, 4, 2]
        num_jobs_per_queue = [
            len(scheduler.get_queue_by_ix(ix).jobs)
            for ix in range(settings.BOTANY_NUM_ROUNDS)
        ]

        self.assertEqual(num_jobs_per_queue, expected_num_jobs_per_queue)


class PlayGameTests(TestCase):
    def test_play_game(self):
        bot1, bot2 = [factories.create_bot() for _ in range(2)]

        actions.play_game(bot1.id, bot2.id)

        models.Game.objects.get(bot1_id=bot1.id, bot2_id=bot2.id)


class ReportResultTest(TestCase):
    def test_report_result(self):
        bot1, bot2 = [factories.create_bot() for _ in range(2)]

        def build_result(score):
            return Result(
                result_type=ResultType.COMPLETE,
                score=score,
                move_list=[0, 1, 4, 7, 8],
                traceback=None,
            )

        actions.report_result(bot1.id, bot2.id, build_result(1))

        game = models.Game.objects.get()

        self.assertEqual(game.bot1_id, bot1.id)
        self.assertEqual(game.bot2_id, bot2.id)
        self.assertEqual(game.score, 1)
        self.assertEqual(game.moves, "01478")

        actions.report_result(bot1.id, bot2.id, build_result(-1))
        actions.report_result(bot2.id, bot1.id, build_result(1))
        actions.report_result(bot2.id, bot1.id, build_result(0))

        self.assertEqual(bot1.bot1_games.count(), 2)
        self.assertEqual(bot1.bot2_games.count(), 2)

        self.assertEqual(bot1.score, -1)
        self.assertEqual(bot2.score, 1)
