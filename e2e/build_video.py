"""Assemble recorded screencast frames into an MP4 at their real timing.  python build_video.py ./rec out.mp4"""
import json
import subprocess
import sys

import imageio_ffmpeg

rec, out = sys.argv[1], sys.argv[2]
stamps = json.load(open(f"{rec}/stamps.json"))
lines = []
for i, t in enumerate(stamps):
    dur = (stamps[i + 1] - t) if i + 1 < len(stamps) else 2.0
    lines += [f"file 'frames/{i:05d}.jpg'", f"duration {max(dur, 0.02):.4f}"]
lines.append(f"file 'frames/{len(stamps) - 1:05d}.jpg'")
open(f"{rec}/list.txt", "w").write("\n".join(lines))
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{rec}/list.txt",
                "-vf", "fps=20,scale=1280:720,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-movflags", "+faststart", out], check=True)
print("wrote", out)
