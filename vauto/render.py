"""컷 편집 + 자막 burn-in + 삐 처리를 ffmpeg 한 번으로 렌더링."""
from .media import pick_encoder, run


def _f(x):
    return f"{x:.3f}"


def render_final(video_src, audio_src, segs, total, beeps, ass_name, out_path, workdir, info, cfg):
    same = str(video_src) == str(audio_src)
    inputs = ["-i", str(video_src)] + ([] if same else ["-i", str(audio_src)])
    v_in, a_in = "0:v", ("0:a" if same else "1:a")

    g = []
    for i, (s, e) in enumerate(segs):
        d = e - s
        fd = min(cfg.fade, d / 4)
        g.append(f"[{v_in}]trim=start={_f(s)}:end={_f(e)},setpts=PTS-STARTPTS[v{i}]")
        g.append(f"[{a_in}]atrim=start={_f(s)}:end={_f(e)},asetpts=PTS-STARTPTS,"
                 f"aformat=sample_rates=48000:channel_layouts=stereo,"
                 f"afade=t=in:d={_f(fd)},afade=t=out:st={_f(d - fd)}:d={_f(fd)}[a{i}]")
    g.append("".join(f"[v{i}][a{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[vc][ac]")

    vchain = []
    if ass_name:
        vchain.append(f"ass={ass_name}:fontsdir=fonts")
    if info.width % 2 or info.height % 2:
        vchain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    g.append(f"[vc]{','.join(vchain) or 'null'}[vout]")

    if beeps:
        cond = "+".join(f"between(t,{_f(a)},{_f(b)})" for a, b in beeps)
        tone = f"0.18*sin(2*PI*1000*t)*gt({cond},0)"
        g.append(f"[ac]volume=0:enable='{cond}'[am]")
        g.append(f"aevalsrc=exprs='{tone}|{tone}':s=48000:c=stereo:d={_f(total)}[bp]")
        g.append("[am][bp]amix=inputs=2:normalize=0:duration=first[aout]")
    else:
        g.append("[ac]anull[aout]")

    script = workdir / "filter.txt"
    script.write_text(";\n".join(g), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-/filter_complex", "filter.txt",
           "-map", "[vout]", "-map", "[aout]", *pick_encoder(cfg.video_quality),
           "-r", info.fps_str, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path)]
    run(cmd, cwd=str(workdir))
