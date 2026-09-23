"""Робот ЕИС: опрашивает публичную RSS-ленту поиска zakupki.gov.ru по сохранённым поискам
и складывает результат в data/tenders.json. Никаких токенов не нужно — это открытая лента.
Если ЕИС недоступна (блокировка по гео, антибот, смена формата) — пишет честный статус в файл,
приложение покажет его пользователю вместо тишины."""
import json, re, sys, time, html, urllib.parse, urllib.request, ssl, datetime as dt
from xml.etree import ElementTree as ET

BASE = "https://zakupki.gov.ru/epz/order/extendedsearch/rss.html"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE  # у ЕИС российский сертификат

def rss_url(s):
    p = {"searchString": s["q"], "morphology": "on", "fz44": "on", "af": "on",
         "pageNumber": "1", "sortDirection": "false", "recordsPerPage": "_50", "sortBy": "UPDATE_DATE",
         "priceFromGeneral": str(s.get("priceFrom", "")), "priceToGeneral": str(s.get("priceTo", "")),
         "currencyIdGeneral": "-1", "OrderPlacementSmallBusinessSubject": "on", "OrderPlacementRnpData": "on",
         "OrderPlacementExecutionRequirement": "on", "orderPlacement94_0": "0", "orderPlacement94_1": "0", "orderPlacement94_2": "0"}
    if s.get("region"): p["deliveryRegionText"] = s["region"]
    return BASE + "?" + urllib.parse.urlencode({k: v for k, v in p.items() if v != ""})

def fetch(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml,application/xml,text/xml,*/*", "Accept-Language": "ru-RU,ru;q=0.9"})
            with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
                return r.status, r.read()
        except Exception as e:
            last = e; time.sleep(3 + i * 4)
    raise last

def money(s):
    m = re.search(r"([\d\s ]+[.,]\d{2})", s or "")
    return float(m.group(1).replace(" ", "").replace(" ", "").replace(",", ".")) if m else None

def field(desc, *names):
    for n in names:
        m = re.search(n + r"\s*:?\s*</?[^>]*>?\s*([^<\n]+)", desc, re.I)
        if m: return html.unescape(m.group(1)).strip(" ;")
    return None

def parse_items(xml_bytes):
    out = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        desc = html.unescape(it.findtext("description") or "")
        num = re.search(r"regNumber=(\d+)", link) or re.search(r"№\s*(\d{15,20})", title)
        number = num.group(1) if num else None
        text = re.sub(r"<[^>]+>", "\n", desc)
        out.append({
            "number": number,
            "title": re.sub(r"^№\s*\d+\s*", "", title).strip(),
            "customer": field(text, "Заказчик", "Организация, осуществляющая размещение") or "",
            "price": money(field(text, "Начальная цена", "Начальная \\(максимальная\\) цена", "Цена") or ""),
            "law": "44-ФЗ" if "44" in (field(text, "Закон") or "44") else "223-ФЗ",
            "published": field(text, "Размещено", "Дата размещения"),
            "deadline": field(text, "Окончание подачи заявок", "Дата окончания подачи заявок"),
            "stage": field(text, "Этап", "Этап размещения"),
            "method": field(text, "Способ определения поставщика", "Способ размещения"),
            "url": link,
            "raw": text.strip()[:1500],
        })
    return out

def main():
    cfg = json.load(open("data/searches.json", encoding="utf-8"))
    result = {"updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "source": "zakupki.gov.ru · RSS", "status": "ok", "searches": [], "tenders": []}
    seen = {}
    errors = []
    for s in cfg["searches"]:
        url = rss_url(s)
        try:
            status, body = fetch(url)
            items = parse_items(body)
            result["searches"].append({"id": s["id"], "name": s["name"], "count": len(items), "http": status})
            for t in items:
                key = t["number"] or t["url"]
                if key in seen:
                    seen[key]["searchIds"].append(s["id"]); continue
                t["searchIds"] = [s["id"]]; seen[key] = t; result["tenders"].append(t)
        except Exception as e:
            errors.append(f"{s['id']}: {type(e).__name__}: {e}")
            result["searches"].append({"id": s["id"], "name": s["name"], "count": 0, "error": str(e)[:300]})
        time.sleep(2)
    if errors and not result["tenders"]:
        result["status"] = "error"; result["message"] = "ЕИС не ответила роботу: " + "; ".join(errors)[:600]
    elif errors:
        result["status"] = "partial"; result["message"] = "Часть поисков не выполнена: " + "; ".join(errors)[:600]
    json.dump(result, open("data/tenders.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: result[k] for k in ("status", "updatedAt")}, ensure_ascii=False), "tenders:", len(result["tenders"]))
    if errors: print("\n".join(errors), file=sys.stderr)

if __name__ == "__main__":
    main()
