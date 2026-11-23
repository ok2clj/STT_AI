"""Decode audio with PyAV's public API, including PyAV 19 (no metadata_errors argument)."""
import itertools

import av
import numpy as np


def decode_audio(path, sampling_rate=16000):
    """Return mono, float32 PCM. Flush resampling so the end of the file is retained."""
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=sampling_rate)
    chunks = []
    with av.open(path, mode="r") as container:
        if not container.streams.audio:
            raise ValueError("Soubor neobsahuje zvukovou stopu.")
        for frame in itertools.chain(container.decode(audio=0), [None]):
            if frame is not None:
                # Concatenate decoded samples independently of discontinuous container timestamps.
                frame.pts = None
            for output in resampler.resample(frame):
                chunks.append(output.to_ndarray().reshape(-1).copy())
    if not chunks:
        return np.empty(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32, copy=False)
