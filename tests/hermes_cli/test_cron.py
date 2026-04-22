"""Tests for hermes_cli.cron command handling."""

from argparse import Namespace

import pytest

from cron.jobs import create_job, get_job, list_jobs
from hermes_cli.cron import cron_command


@pytest.fixture()
def tmp_cron_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("cron.jobs.CRON_DIR", tmp_path / "cron")
    monkeypatch.setattr("cron.jobs.JOBS_FILE", tmp_path / "cron" / "jobs.json")
    monkeypatch.setattr("cron.jobs.OUTPUT_DIR", tmp_path / "cron" / "output")
    return tmp_path


class TestCronCommandLifecycle:
    def test_pause_resume_run(self, tmp_cron_dir, capsys):
        job = create_job(prompt="Check server status", schedule="every 1h")

        cron_command(Namespace(cron_command="pause", job_id=job["id"]))
        paused = get_job(job["id"])
        assert paused["state"] == "paused"

        cron_command(Namespace(cron_command="resume", job_id=job["id"]))
        resumed = get_job(job["id"])
        assert resumed["state"] == "scheduled"

        cron_command(Namespace(cron_command="run", job_id=job["id"]))
        triggered = get_job(job["id"])
        assert triggered["state"] == "scheduled"

        out = capsys.readouterr().out
        assert "Paused job" in out
        assert "Resumed job" in out
        assert "Triggered job" in out

    def test_edit_can_replace_and_clear_skills(self, tmp_cron_dir, capsys):
        job = create_job(
            prompt="Combine skill outputs",
            schedule="every 1h",
            skill="blogwatcher",
        )

        cron_command(
            Namespace(
                cron_command="edit",
                job_id=job["id"],
                schedule="every 2h",
                prompt="Revised prompt",
                name="Edited Job",
                deliver=None,
                repeat=None,
                skill=None,
                skills=["maps", "blogwatcher"],
                clear_skills=False,
            )
        )
        updated = get_job(job["id"])
        assert updated["skills"] == ["maps", "blogwatcher"]
        assert updated["name"] == "Edited Job"
        assert updated["prompt"] == "Revised prompt"
        assert updated["schedule_display"] == "every 120m"

        cron_command(
            Namespace(
                cron_command="edit",
                job_id=job["id"],
                schedule=None,
                prompt=None,
                name=None,
                deliver=None,
                repeat=None,
                skill=None,
                skills=None,
                clear_skills=True,
            )
        )
        cleared = get_job(job["id"])
        assert cleared["skills"] == []
        assert cleared["skill"] is None

        out = capsys.readouterr().out
        assert "Updated job" in out

    def test_create_with_multiple_skills(self, tmp_cron_dir, capsys):
        cron_command(
            Namespace(
                cron_command="create",
                schedule="every 1h",
                prompt="Use both skills",
                name="Skill combo",
                deliver=None,
                repeat=None,
                skill=None,
                skills=["blogwatcher", "maps"],
            )
        )
        out = capsys.readouterr().out
        assert "Created job" in out

        jobs = list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["skills"] == ["blogwatcher", "maps"]
        assert jobs[0]["name"] == "Skill combo"

    def test_create_reactive_only_job_with_prompt_positionals(self, tmp_cron_dir, capsys):
        source = create_job(prompt="Source", schedule="every 1h")

        cron_command(
            Namespace(
                cron_command="create",
                schedule="Repair the failing source job",
                prompt=None,
                name="Repair job",
                deliver=None,
                repeat=None,
                skill=None,
                skills=None,
                script=None,
                trigger_job_id=source["id"],
                trigger_after_failures=2,
                reactive_only=True,
            )
        )

        out = capsys.readouterr().out
        assert "Created job" in out
        jobs = list_jobs()
        repair = [job for job in jobs if job["id"] != source["id"]][0]
        assert repair["schedule"] is None
        assert repair["reactive_trigger"]["job_id"] == source["id"]

    def test_list_shows_health_and_reactive_trigger(self, tmp_cron_dir, capsys):
        source = create_job(prompt="Source", schedule="every 1h", name="Source")
        repair = create_job(
            prompt="Repair",
            reactive_trigger={
                "job_id": source["id"],
                "after_consecutive_failures": 2,
            },
            name="Repair",
        )

        from cron.jobs import mark_job_run
        mark_job_run(source["id"], success=False, error="boom")

        cron_command(Namespace(cron_command="list", all=False))
        out = capsys.readouterr().out
        assert "Reactive:" in out
        assert repair["id"] in out
        assert "Health:" in out
