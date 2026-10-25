"""Finto sdxl_train_network.py: stampa righe come kohya (anche con \\r di tqdm) e salva le epoche."""
import argparse
import os
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--output_dir")
ap.add_argument("--output_name")
ap.add_argument("--max_train_epochs", type=int)
ap.add_argument("--dataset_config")
a, _ = ap.parse_known_args()

print("prepare tokenizers")
print("caching latents...")
if os.environ.get("FINTO_KOHYA_ERRORE") == "oom":
    print("Traceback (most recent call last):")
    print("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 MiB")
    sys.exit(1)
print("running training / 学習開始")
print(f"  num epochs / epoch数: {a.max_train_epochs}")
passi_per_epoca = 5
totale = passi_per_epoca * a.max_train_epochs
passo = 0
for e in range(1, a.max_train_epochs + 1):
    print(f"\nepoch {e}/{a.max_train_epochs}")
    for _ in range(passi_per_epoca):
        passo += 1
        loss = 0.15 / (1 + passo * 0.1)
        sys.stdout.write(f"\rsteps:  {passo * 100 // totale}%|███     | {passo}/{totale} [00:0{e}<00:10,  2.10it/s, avr_loss={loss:.4f}]")
        sys.stdout.flush()
        time.sleep(0.002)
    nome = f"{a.output_name}.safetensors" if e == a.max_train_epochs else f"{a.output_name}-{e:06d}.safetensors"
    f = Path(a.output_dir) / nome
    f.write_bytes(b"lora" * 10)
    print(f"\nsaving checkpoint: {f}")
print("model saved.")
