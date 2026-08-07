"""qsub CLI — argparse only (Spec §21–§22)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from qsub_core import __version__, errors
from qsub_core.events import EventEmitter
from qsub_core.logging_util import setup_logging
from qsub_core.media.probe import ProbeError, probe_media
from qsub_core.pipeline.engine import PipelineEngine, TranscribeOptions
from qsub_core.system.doctor import run_doctor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qsub",
        description="QwenSubtitle CLI — 本地离线字幕生成",
    )
    parser.add_argument("--version", action="version", version=f"QwenSubtitle {__version__}")
    sub = parser.add_subparsers(dest="command")

    # doctor
    p_doc = sub.add_parser("doctor", help="检查运行环境与模型")
    p_doc.add_argument("--json", action="store_true", help="输出 JSON（供 GUI 使用）")

    # probe
    p_probe = sub.add_parser("probe", help="探测媒体音轨信息")
    p_probe.add_argument("input", type=Path, help="视频或音频文件")
    p_probe.add_argument("--json", action="store_true", help="输出 JSON")

    # transcribe
    p_tr = sub.add_parser(
        "transcribe",
        help="转录并生成字幕（Phase 4：ASR + ForcedAlign / resume）",
    )
    p_tr.add_argument("input", type=Path, help="输入媒体文件")
    p_tr.add_argument("--output", type=Path, default=None, help="输出 .srt 路径（Phase 5 起生效）")
    p_tr.add_argument("--language", default="auto", help="auto | Chinese | English | ...")
    p_tr.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    p_tr.add_argument(
        "--audio-stream",
        default="auto",
        help="auto 或音轨 index",
    )
    p_tr.add_argument("--mode", choices=["safe"], default="safe")
    p_tr.add_argument("--resume", dest="resume", action="store_true", default=True)
    p_tr.add_argument("--no-resume", dest="resume", action="store_false")
    p_tr.add_argument("--work-dir", type=Path, default=None)
    p_tr.add_argument("--keep-work", action="store_true")
    p_tr.add_argument("--overwrite", action="store_true")
    p_tr.add_argument("--events", choices=["text", "ndjson"], default="text")
    p_tr.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error"],
        default="info",
    )

    # export (stub — Phase 5)
    p_ex = sub.add_parser("export", help="从 project.json 导出字幕（Phase 5）")
    p_ex.add_argument("project", type=Path)
    p_ex.add_argument("--format", default="srt", choices=["srt"])
    p_ex.add_argument("--output", type=Path, default=None)
    p_ex.add_argument("--encoding", choices=["utf-8", "utf-8-bom"], default="utf-8-bom")

    return parser


def cmd_probe(args: argparse.Namespace) -> int:
    try:
        result = probe_media(args.input)
    except ProbeError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return errors.FFPROBE_FAILURE

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return errors.SUCCESS

    print(f"Path:      {result['path']}")
    print(f"Container: {result.get('container')}")
    dur = result.get("duration")
    if dur is not None:
        m, s = divmod(float(dur), 60.0)
        print(f"Duration:  {int(m):02d}:{s:06.3f} ({dur:.3f}s)")
    streams = result.get("audio_streams") or []
    print(f"Audio:     {len(streams)} stream(s)")
    for st in streams:
        flag = " [default]" if st.get("default") else ""
        lang = st.get("language") or "?"
        print(
            f"  #{st['index']}: {st.get('codec')} "
            f"{st.get('channels')}ch {st.get('sample_rate')}Hz lang={lang}{flag}"
        )
    return errors.SUCCESS


def cmd_transcribe(args: argparse.Namespace) -> int:
    setup_logging(args.log_level)
    events = EventEmitter(mode=args.events)
    opts = TranscribeOptions(
        input_path=args.input,
        output=args.output,
        language=args.language,
        device=args.device,
        audio_stream=str(args.audio_stream),
        mode=args.mode,
        resume=bool(args.resume),
        work_dir=args.work_dir,
        keep_work=bool(args.keep_work),
        overwrite=bool(args.overwrite),
        events=args.events,
        log_level=args.log_level,
    )
    return PipelineEngine(opts, events).run()


def cmd_export(args: argparse.Namespace) -> int:
    print(
        "export 将在 Phase 5 实现（project.json → SRT/VTT/ASS）。",
        file=sys.stderr,
    )
    return errors.INVALID_ARGS


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return errors.SUCCESS

    if args.command == "doctor":
        return run_doctor(as_json=bool(args.json))
    if args.command == "probe":
        return cmd_probe(args)
    if args.command == "transcribe":
        return cmd_transcribe(args)
    if args.command == "export":
        return cmd_export(args)

    parser.error(f"unknown command: {args.command}")
    return errors.INVALID_ARGS


if __name__ == "__main__":
    raise SystemExit(main())
