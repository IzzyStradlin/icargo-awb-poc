"""Patch awb_document_presplitter.py: use full image instead of body strip."""
path = r"app\extraction\awb_document_presplitter.py"

with open(path, encoding="utf-8") as f:
    content = f.read()

old_kw = (
    '        _AWB_KEYWORDS = frozenset({\n'
    '            "shipper", "consignee", "air waybill", "waybill", "hawb",\n'
    '            "manifest", "master", "flight", "departure", "destination",\n'
    '            "pieces", "weight", "sender", "notify",\n'
    '        })'
)
new_kw = (
    '        _AWB_KEYWORDS = frozenset({\n'
    '            "shipper", "consignee", "air waybill", "waybill", "hawb",\n'
    '            "manifest", "master", "flight", "departure", "destination",\n'
    '            "pieces", "weight", "sender", "notify", "house",\n'
    '            "apt dest", "hawb n", "nature of goods", "chargeable",\n'
    '            "issuing carrier", "gross weight",\n'
    '        })'
)

old_body = (
    '            strip_h = max(1, int(h * 0.25))\n'
    '            body = img_arr[strip_h:, :, :]\n'
    '            cfg_probe = "--oem 1 --psm 6"\n'
    '\n'
    '            def _kw_score_kw(arr) -> int:\n'
    '                txt = _tess.image_to_string(\n'
    '                    _PILImage.fromarray(arr), lang="eng", config=cfg_probe\n'
    '                ).lower()\n'
    '                return sum(1 for kw in _AWB_KEYWORDS if kw in txt)\n'
    '\n'
    '            _CORRECTION = {0: 0, 1: 90, 2: 180, 3: 270}\n'
    '            scores: dict[int, int] = {}\n'
    '            for k in (0, 1, 2, 3):\n'
    '                scores[k] = _kw_score_kw(_np.rot90(body, k=k) if k else body)'
)
new_body = (
    '            cfg_probe = "--oem 1 --psm 6"\n'
    '\n'
    '            def _kw_score_kw(arr) -> int:\n'
    '                txt = _tess.image_to_string(\n'
    '                    _PILImage.fromarray(arr), lang="eng", config=cfg_probe\n'
    '                ).lower()\n'
    '                return sum(1 for kw in _AWB_KEYWORDS if kw in txt)\n'
    '\n'
    '            _CORRECTION = {0: 0, 1: 90, 2: 180, 3: 270}\n'
    '            scores: dict[int, int] = {}\n'
    '            for k in (0, 1, 2, 3):\n'
    '                scores[k] = _kw_score_kw(_np.rot90(img_arr, k=k) if k else img_arr)'
)

changed = False
if old_kw in content:
    content = content.replace(old_kw, new_kw, 1)
    print("Keyword set expanded OK")
    changed = True
else:
    print("WARNING: old keyword set not found!")

if old_body in content:
    content = content.replace(old_body, new_body, 1)
    print("Body strip → full image OK")
    changed = True
else:
    print("WARNING: body strip pattern not found!")

if changed:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("File written.")
