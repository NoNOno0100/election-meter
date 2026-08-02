# מד הבחירות — Israeli Election Forecast (100% free stack)

צנרת שלמה: סקרים מוויקיפדיה → אגרגציה עם house effects → מונטה קרלו → בדר־עופר
(כולל אחוז חסימה 3.25% והסכמי עודפים) → `forecast.json` → דשבורד סטטי.

## 🌐 אתר חי
**https://NoNOno0100.github.io/election-meter/**

ריפו: https://github.com/NoNOno0100/election-meter

## קבצים
| קובץ | תפקיד |
|---|---|
| `scrape_polls.py` | מושך את כל סקרי המנדטים מוויקיפדיה → `polls.csv` |
| `bader_ofer.py` | מנוע חלוקת מנדטים. **מאומת מול תוצאות 2022 הרשמיות (1:1)** |
| `model.py` | שקלול (רעננות + מדגם + הטיות מכון) + 20K סימולציות → `forecast.json` |
| `index.html` | דשבורד RTL בעברית שקורא את `forecast.json` — ללא תלות בשרת |
| `.github/workflows/daily.yml` | עדכון יומי אוטומטי (GitHub Actions) |

## הרצה מקומית
```bash
pip install requests pandas lxml beautifulsoup4 numpy
python scrape_polls.py     # -> polls.csv
python model.py            # -> forecast.json + הדפסת תחזית
python -m http.server      # פתח http://localhost:8000
```

## אוטומציה יומית (0 ש\"ח — GitHub Actions + Pages)
- **Cron:** `0 16 * * *` (19:00 שעון ישראל בקיץ) + `workflow_dispatch`
- אם הגירוד/המודל נכשלים — **אין commit**, והאתר נשאר עם `forecast.json` האחרון התקין

### הרצה ידנית של ה־workflow
```bash
gh workflow run daily.yml --repo NoNOno0100/election-meter
# או: Actions → daily-forecast → Run workflow
```

## מקורות (הכול חינם)
- סקרים: https://en.wikipedia.org/wiki/Opinion_polling_for_the_2026_Israeli_legislative_election
- תוצאות אמת: https://data.gov.il ואתרי ועדת הבחירות

## עמידות
- User-Agent מזוהה (`ElectionMeter/0.1`), בקשה אחת ליום, בלי retry אגרסיבי
- ולידציה לפני commit: JSON תקין + ≥8 מפלגות + סכום מנדטים 115–125
- כישלון בריצה לילית → האתר ממשיך להציג את הנתונים הקודמים
