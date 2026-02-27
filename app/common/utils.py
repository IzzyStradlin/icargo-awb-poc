# app/common/utils.py
def safe_get(dct, key, default=None):
    try:
        return dct.get(key, default)
    except Exception:
        return default