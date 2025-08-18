
import argparse, secrets, string

def gen_urlsafe(nbytes: int) -> str:
    # token_urlsafe returns Base64URL (A–Z a–z 0–9 - _), no '=' padding
    return secrets.token_urlsafe(nbytes)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Generate a random API key")
    p.add_argument("--bytes", type=int, default=48, help="random bytes (default: 48 ≈ 64 chars)")
    args = p.parse_args()
    key = gen_urlsafe(args.bytes)
    print(key)
