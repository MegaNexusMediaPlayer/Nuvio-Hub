"""First-run skips, PIN cancellation and watched-status regression checks."""
import importlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock
import kodi_stub
import frontend_test_support
frontend_test_support.install()
wizard=importlib.import_module('nuvio_ui.onboarding')
account=importlib.import_module('nuvio_ui.simkl_account')
simkl=account.simkl
companion=kodi_stub.import_lib_module('companion')


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        for patch in (mock.patch.object(wizard.sync.Nuvio,'is_linked',return_value=False),mock.patch('resources.lib.simkl.authorized',return_value=False)):
            patch.start();self.addCleanup(patch.stop)

    def addon(self,values):
        return SimpleNamespace(getSetting=lambda k:values.get(k,''),setSetting=lambda k,v:values.__setitem__(k,v))

    def test_skip_setup_keeps_existing_providers_and_choices(self):
        values={'providers_json':'personal','nuvio_metadata_provider':'chosen','nuvio_auto_trailers':'false'}
        action=mock.Mock();dialog=mock.Mock();dialog.select.return_value=3
        with mock.patch.object(wizard,'ADDON',self.addon(values)),mock.patch.object(wizard,'_steps',return_value=[('Nuvio account',[('Connect',action)])]),mock.patch.object(wizard.xbmcgui,'Dialog',return_value=dialog):wizard.run(force=True)
        action.assert_not_called()
        self.assertEqual(values['providers_json'],'personal');self.assertEqual(values['nuvio_metadata_provider'],'chosen')
        self.assertEqual(values['nuvio_auto_trailers'],'false');self.assertEqual(values['nuvio_setup_v110_done'],'true')

    def test_back_remembers_step_and_skip_does_not_invoke_action(self):
        values={};action=mock.Mock();dialog=mock.Mock();dialog.select.side_effect=[2,-1]
        steps=[('Account',[('Connect',action)]),('Metadata',[('Choose',action)])]
        with mock.patch.object(wizard,'ADDON',self.addon(values)),mock.patch.object(wizard,'_steps',return_value=steps),mock.patch.object(wizard.xbmcgui,'Dialog',return_value=dialog):wizard.run()
        action.assert_not_called();self.assertEqual(values['nuvio_setup_v110_step'],'1')
        self.assertNotIn('nuvio_setup_v110_done',values)

    def test_completed_wizard_does_not_repeat(self):
        with mock.patch.object(wizard,'ADDON',self.addon({'nuvio_setup_v110_done':'true'})),mock.patch.object(wizard,'_steps') as steps:wizard.run()
        steps.assert_not_called()

    def test_first_step_connects_nuvio_and_simkl_is_included(self):
        steps=wizard._steps()
        self.assertEqual(steps[0][1][0][1],wizard.settings.sign_in_nuvio)
        self.assertTrue(any(action==account.link for _,actions in steps for _,action in actions))
        self.assertFalse(any('stremio' in title.lower() for title,_ in steps))

    def test_cancelled_pin_dialog_does_not_save_a_token(self):
        dialog=mock.Mock();dialog.iscanceled.return_value=True
        with mock.patch.object(simkl,'authorized',return_value=False),mock.patch.object(account,'job',return_value={'user_code':'1234'}),mock.patch.object(account.xbmcgui,'DialogProgress',return_value=dialog),mock.patch.object(simkl,'save_token') as save:
            self.assertFalse(account.link())
        save.assert_not_called();dialog.close.assert_called()

    def test_pin_success_commits_token_and_enables_tracking(self):
        values={};dialog=mock.Mock();dialog.iscanceled.return_value=False
        monitor=SimpleNamespace(abortRequested=lambda:False,waitForAbort=lambda n:False)
        def thread(target,**kwargs):return SimpleNamespace(start=target)
        with mock.patch.object(account,'ADDON',self.addon(values)),mock.patch.object(simkl,'authorized',return_value=False),mock.patch.object(account,'job',return_value={'user_code':'1234'}),mock.patch.object(account.xbmcgui,'DialogProgress',return_value=dialog),mock.patch.object(account.xbmcgui,'Dialog'),mock.patch.object(account.xbmc,'Monitor',return_value=monitor),mock.patch.object(account.threading,'Thread',side_effect=thread),mock.patch.object(simkl,'_request',return_value={'access_token':'test-only'}),mock.patch.object(simkl,'save_token',return_value=True) as save:
            self.assertTrue(account.link())
        self.assertEqual(save.call_args.args[0]['access_token'],'test-only')
        self.assertEqual(values['simkl_mark_watched'],'true')
        self.assertEqual(dialog.create.call_args.args[0],'Simkl PIN: 1234')
        self.assertIn('1234',dialog.create.call_args.args[1].splitlines()[0])

    def test_pin_instructions_are_english(self):
        message=simkl._build_pin_message('https://simkl.com/pin','1234',60)
        self.assertIn('Open on your phone',message)
        self.assertFalse(any('\u0600'<=c<='\u06ff' for c in message))

    def test_pin_is_visible_without_scrolling_in_short_progress_textbox(self):
        for remaining in (None,900,1,0):
            lines=simkl._build_pin_message('https://simkl.com/pin','ABCD1234',remaining).splitlines()
            self.assertEqual(lines[0],'[B]PIN: ABCD1234[/B]')
            self.assertIn('https://simkl.com/pin',lines[1])
            self.assertEqual(len(lines),3)
            self.assertTrue(all(lines))

    def test_failed_token_write_preserves_previous_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'token.json';path.write_text('previous')
            with mock.patch.object(simkl.os,'replace',side_effect=OSError):self.assertFalse(simkl._write_json(str(path),{'access_token':'new'}))
            self.assertEqual(path.read_text(),'previous');self.assertEqual(len(list(Path(tmp).iterdir())),1)

    def test_reporter_only_flushes_the_durable_journal(self):
        reporter=companion.SimklReporter()
        with mock.patch.object(companion.simkl,'flush_progress',return_value=0) as flush,mock.patch.object(companion.simkl,'queue_progress') as queue:
            self.assertFalse(reporter.stopped({},0))
            reporter.ended({'duration_ms':100000},0)
            self.assertEqual(flush.call_count,2);queue.assert_not_called()

    def test_manual_stop_still_uses_threshold_and_deduplicates(self):
        ctx={'duration_ms':100000,'media_type':'movie','imdb_id':'tt123','video_id':'tt123'}
        with mock.patch.object(simkl,'enabled',return_value=True),mock.patch.object(simkl,'authorized',return_value=True),mock.patch.object(simkl,'mark_watched_enabled',return_value=True),mock.patch.object(simkl,'watched_threshold_percent',return_value=85),mock.patch.object(simkl,'_MARKED_THIS_SESSION',set()),mock.patch.object(simkl,'_request',return_value={}) as request:
            self.assertFalse(simkl.mark_watched_from_ctx(ctx,20000))
            self.assertTrue(simkl.mark_watched_from_ctx(ctx,95000))
            self.assertFalse(simkl.mark_watched_from_ctx(ctx,100000))
        self.assertEqual(request.call_count,1)
