import pytest

from c1_requirement_quality.cli import build_parser, main


def test_reads_run_options():
    args = build_parser().parse_args(["run", "--srs", "srs.md", "--out", "runs/RUN-1"])
    assert args.srs == "srs.md"
    assert args.out == "runs/RUN-1"


def test_rejects_missing_out():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--srs", "srs.md"])


def test_run_creates_c1_folder(tmp_path):
    assert main(["run", "--srs", "srs.md", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "c1").is_dir()
