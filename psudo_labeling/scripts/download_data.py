"""Download the ReviewArena ICML split and save it locally."""
from datasets import load_dataset

ds = load_dataset("Samarth0710/reviewarena", split="icml")
print(ds)
ds.save_to_disk("data/reviewarena_icml")
print("saved to data/reviewarena_icml")
