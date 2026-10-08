"""Original score + SFX for the EcoCatcher brag video (D major, 100 BPM, 24.6 s)."""
import numpy as np, wave

SR = 48000
DUR = 24.6
BEAT = 0.6
N = int(SR * (DUR + 0.05))
rng = np.random.default_rng(7)

def hz(m): return 440.0 * 2 ** ((m - 69) / 12)
def tvec(d): return np.arange(int(SR * d)) / SR

music = np.zeros((2, N)); sfx = np.zeros((2, N))
def put(buf, sig, t0, gain=1.0, pan=0.0):
    i = int(t0 * SR)
    if i < 0: sig = sig[-i:]; i = 0
    j = min(N, i + sig.shape[-1])
    if j <= i: return
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[0, i:j] += sig[: j - i] * gain * l * 1.414
    buf[1, i:j] += sig[: j - i] * gain * r * 1.414

def lowpass(x, fc):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X / np.sqrt(1 + (f / fc) ** 4), len(x))

# ---------- chord timeline (in beats) ----------
D, Bm, G, A, Asus = [50, 57, 61, 66], [47, 54, 57, 62], [43, 55, 59, 62], [45, 57, 61, 64], [45, 57, 62, 64]
CH = [(0, 4, D), (4, 8, Bm), (8, 12, G), (12, 16, A), (16, 20, D), (20, 24, Bm), (24, 28, G),
      (28, 32, Asus), (32, 35, A), (35, 41, D)]

# ---------- pad: soft additive saw, slow swell ----------
def pad_note(f, d):
    t = tvec(d); x = np.zeros_like(t)
    for det in (-0.12, 0.0, 0.11):
        ff = f * 2 ** (det / 12)
        for n in range(1, 9):
            x += np.sin(2 * np.pi * ff * n * t + n) / n ** 1.6
    a, r = 0.55, 0.8
    env = np.minimum(1, t / a) * np.clip((d - t) / r, 0, 1)
    return x * env
for b0, b1, ch in CH:
    t0, d = b0 * BEAT, (b1 - b0) * BEAT + 0.7
    if b1 == 41: d = DUR - t0 + 0.05
    for k, m in enumerate(ch[1:]):
        put(music, pad_note(hz(m), d), t0 - 0.05, 0.022, pan=(-0.4, 0.0, 0.4)[k])

# ---------- pluck arpeggio (from the reveal) ----------
def pluck(f, d=0.9, bright=1.0):
    t = tvec(d)
    x = np.sin(2 * np.pi * f * t) + 0.35 * bright * np.sin(4 * np.pi * f * t) * np.exp(-t * 9)
    return x * np.exp(-t * 5.5) * np.minimum(1, t / 0.004)
ARP = [0, 1, 2, 3, 2, 1, 3, 2]
for b in range(5 * 2, 41 * 2):            # eighth notes from 3.0 s
    beat = b / 2
    ch = next(c for b0, b1, c in CH if b0 <= beat < b1)
    tones = [m + 12 for m in ch[1:]] + [ch[1] + 24]
    m = tones[ARP[b % 8]]
    g = 0.11 if b % 2 == 0 else 0.075
    if beat >= 35: g *= max(0, 1 - (beat - 35) / 4)   # thin out under the outro
    put(music, pluck(hz(m)), beat * BEAT, g, pan=0.35 if b % 2 else -0.35)

# ---------- bass + kick + shaker (S3..S5) ----------
def kick():
    t = tvec(0.35); f = 45 + 75 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11)
def shaker():
    t = tvec(0.07); n = rng.standard_normal(len(t)); n = np.diff(n, prepend=0)
    return lowpass(n * np.exp(-t * 60), 6500)
def bass(f, d):
    t = tvec(d); return (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t)) * np.exp(-t * 2.4) * np.minimum(1, t / 0.01)
for bt in range(11, 35):
    ch = next(c for b0, b1, c in CH if b0 <= bt < b1)
    if bt % 2 == 1: put(music, kick(), bt * BEAT, 0.30)
    put(music, bass(hz(ch[0] - 12), 0.9), bt * BEAT, 0.15 if bt % 2 == 1 else 0.09)
    put(music, shaker(), bt * BEAT + BEAT / 2, 0.035, pan=0.2)
    put(music, shaker(), bt * BEAT, 0.015, pan=-0.2)
# low D root under the hook and the outro
put(music, bass(hz(38), 2.6), 0.0, 0.12)
put(music, bass(hz(38), 3.4), 35 * BEAT, 0.2)

# ---------- SFX in the same key ----------
def marimba(f, d=0.9):
    t = tvec(d)
    x = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t * 30) + 0.04 * np.sin(2 * np.pi * 9.9 * f * t) * np.exp(-t * 60)
    return x * np.exp(-t * 7) * np.minimum(1, t / 0.002)
def bell(f, d=3.5):
    t = tvec(d); x = np.zeros_like(t)
    for ratio, amp, dec in [(1, 1, 1.1), (2.0, .5, 1.6), (2.76, .35, 2.2), (5.4, .18, 4), (8.93, .08, 6)]:
        x += amp * np.sin(2 * np.pi * f * ratio * t) * np.exp(-t * dec)
    return x * np.minimum(1, t / 0.003)
def swell(d, f0=300, f1=2400):
    t = tvec(d); n = rng.standard_normal(len(t))
    x = lowpass(n, 900) * (t / d) ** 2 * np.clip((d - t) / 0.08, 0, 1)
    return x / (np.abs(x).max() + 1e-9)
def tick():
    t = tvec(0.05); n = np.diff(rng.standard_normal(len(t)), prepend=0)
    return n * np.exp(-t * 220) + 0.5 * np.sin(2 * np.pi * hz(86) * t) * np.exp(-t * 90)

put(sfx, marimba(hz(62), 1.4), 0.12, 0.22)                       # "Baku."
put(sfx, marimba(hz(69)), 0.85, 0.22, pan=0.15)                  # "31 °C outside."
put(sfx, swell(0.55), 2.45, 0.10)                                # into the reveal
put(sfx, marimba(hz(78), 0.6), 4.9, 0.13, pan=-0.2)              # underline "Baku, Azerbaijan"
put(sfx, tick(), 9.0, 0.30, pan=0.2)                             # cursor click
for k, m in enumerate([74, 78, 81]):                             # upgrades switch on
    put(sfx, marimba(hz(m), 0.8), 9.06 + k * 0.075, 0.15, pan=-0.2 + 0.2 * k)
for k, m in enumerate([69, 74, 78]):                             # three standards cards
    put(sfx, marimba(hz(m)), 13.2 + k * 0.6, 0.20, pan=0.25)
for k, m in enumerate([74, 78, 81]):                             # three Baku figures
    put(sfx, marimba(hz(m)), 17.1 + k * 0.6, 0.18, pan=-0.25)
put(sfx, swell(0.6), 20.4, 0.10)                                 # into the outro
put(sfx, bell(hz(74)), 21.0, 0.17)                               # seal
put(sfx, bell(hz(81), 3.0), 21.4, 0.07, pan=0.2)

# ---------- shared room: one reverb for music and SFX ----------
def reverb(x, sec=2.2, wet=0.22):
    L = int(SR * sec); t = np.arange(L) / SR
    out = np.zeros_like(x)
    for c in range(2):
        ir = rng.standard_normal(L) * np.exp(-t * 3.2); ir = lowpass(ir, 4500); ir[: int(0.012 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        n = 1 << int(np.ceil(np.log2(x.shape[1] + L)))
        out[c] = np.fft.irfft(np.fft.rfft(x[c], n) * np.fft.rfft(ir, n), n)[: x.shape[1]]
    return x * (1 - wet) + out * wet * 2.2

mix = reverb(music, wet=0.25) + reverb(sfx, wet=0.32)
def hp(x, fc=32):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR); return np.fft.irfft(X * (f / fc) ** 2 / np.sqrt(1 + (f / fc) ** 4), len(x))
mix = np.vstack([hp(lowpass(mix[0], 14000)), hp(lowpass(mix[1], 14000))])
t = np.arange(N) / SR
mix *= np.minimum(1, t / 0.02) * np.clip((DUR - t) / 0.9, 0, 1)   # gentle tail fade
mix = np.tanh(mix / 0.9) * 0.9                                    # soft limit
mix *= 10 ** (-1.0 / 20) / np.abs(mix).max()
rms = np.sqrt((mix ** 2).mean()); print('peak -1 dBFS, rms dBFS %.1f' % (20 * np.log10(rms)))
pcm = (mix.T * 32767).astype(np.int16)
with wave.open('score.wav', 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
