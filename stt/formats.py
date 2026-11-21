"""Subtitle formatting without an inference dependency."""
import json
import math


def timestamp(seconds, separator=","):
    if not math.isfinite(seconds):
        raise ValueError("Invalid timestamp")
    ms = max(0, round(seconds * 1000))
    hours, rest = divmod(ms, 3600000)
    minutes, rest = divmod(rest, 60000)
    sec, ms = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{sec:02}{separator}{ms:03}"


def format_transcript(job, fmt):
    segments = job["segments"]
    if fmt == "json":
        return json.dumps(job, ensure_ascii=False, indent=2)
    if fmt == "txt":
        return "\n".join(s["text"] for s in segments) + "\n"
    if fmt not in ("srt", "vtt"):
        raise ValueError("Unsupported format")
    sep = "." if fmt == "vtt" else ","
    content = "WEBVTT\n\n" if fmt == "vtt" else ""
    for i, s in enumerate(segments, 1):
        text = " ".join(s["text"].split()).replace("-->", "→")
        content += f"{i}\n{timestamp(s['start'], sep)} --> {timestamp(s['end'], sep)}\n{text}\n\n"
    return content
