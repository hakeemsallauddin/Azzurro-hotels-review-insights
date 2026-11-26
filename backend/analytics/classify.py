"""Deterministic, transparent review sentiment and multi-label topic tagging."""
import json, re

TOPICS = {
 "Cleanliness": ["clean", "cleanliness", "dirty", "dust", "stain", "smell", "hygiene", "mould", "mold"],
 "Check-in experience": ["check in", "check-in", "checkin", "check out", "reception", "key card", "keys", "arrival"],
 "Staff behaviour": ["staff", "receptionist", "host", "service", "rude", "friendly", "helpful", "unhelpful"],
 "Noise": ["noise", "noisy", "loud", "soundproof", "traffic", "thin walls", "quiet"],
 "Facilities": ["facility", "facilities", "pool", "gym", "elevator", "lift", "wifi", "wi-fi", "laundry", "kitchen"],
 "Location": ["location", "located", "train", "station", "transport", "walkable", "central", "area", "distance"],
 "Room condition": ["room", "bed", "mattress", "bathroom", "shower", "air conditioning", "aircon", "accommodation", "dated"],
 "Value for money": ["value", "price", "expensive", "overpriced", "worth", "cost", "cheap", "money"],
}
NEGATIONS = re.compile(r"\b(no|not|never|without|isn't|wasn't|aren't|weren't|hardly)\b", re.I)
POS = {"good","great","excellent","love","lovely","comfortable","clean","friendly","helpful","perfect","beautiful","enjoyed","recommend","easy","convenient"}
NEG = {"bad","poor","terrible","dirty","uncomfortable","rude","broken","noisy","awful","disappointed","issue","problem","small","old","expensive","worst"}

def classify(rating, positive_text="", negative_text=""):
    try: score = float(rating) if rating is not None else None
    except (TypeError, ValueError): score = None
    text = f"{positive_text} {negative_text}".lower()
    words = re.findall(r"[a-z']+", text)
    polarity = sum(w in POS for w in words) - sum(w in NEG for w in words)
    if score is None:
        sentiment = "positive" if polarity >= 2 else "negative" if polarity <= -2 else "neutral"
    elif score >= 8:
        sentiment = "positive"
    elif score < 6:
        sentiment = "negative"
    else:
        if polarity >= 2: sentiment = "positive"
        elif polarity <= -2: sentiment = "negative"
        else: sentiment = "neutral"
    tagged = []
    for topic, terms in TOPICS.items():
        if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms):
            tagged.append(topic)
    return sentiment, tagged

def classify_issue_topics(sentiment, negative_text=""):
    """Tag operational issues only from the guest's negative comment text."""
    if sentiment != "negative":
        return []
    text = (negative_text or "").lower()
    return [topic for topic, terms in TOPICS.items()
            if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms)]

def classify_praise_topics(sentiment, positive_text=""):
    """Tag praise only from the positive comment, never from complaint text."""
    if sentiment != "positive":
        return []
    text = (positive_text or "").lower()
    return [topic for topic, terms in TOPICS.items()
            if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms)]

def persist_classifications(db):
    rows = db.execute("SELECT id,rating,positive_text,negative_text FROM reviews").fetchall()
    for row in rows:
        sentiment, topics = classify(row["rating"], row["positive_text"], row["negative_text"])
        issue_topics = classify_issue_topics(sentiment, row["negative_text"])
        praise_topics = classify_praise_topics(sentiment, row["positive_text"])
        db.execute("UPDATE reviews SET sentiment=?, topics=?, issue_topics=?, praise_topics=? WHERE id=?", (sentiment,json.dumps(topics),json.dumps(issue_topics),json.dumps(praise_topics),row["id"]))
