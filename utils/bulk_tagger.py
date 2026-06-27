"""
bulk_tagger.py — adds missing region + category tags to data.json entries.
Rules:
  - Never removes existing tags
  - Adds region tag from TLD if no 2-letter tag / 'global' present
  - Adds category tag from engine type or URL keywords if no official category tag present
  - Conservative: skips if uncertain
"""
import json, re
from urllib.parse import urlparse
from collections import Counter

# ── Region: TLD → ISO code ───────────────────────────────────────────────────
TLD_REGION = {
    'ru': 'ru', 'su': 'ru',
    'xn--p1ai': 'ru',   # Cyrillic .рф
    'ua': 'ua', 'by': 'by', 'kz': 'kz', 'az': 'az',
    'kg': 'kg', 'uz': 'uz', 'md': 'md',
    'ge': 'ge', 'tj': 'tj',
    'de': 'de', 'at': 'at', 'ch': 'ch',
    'fr': 'fr',
    'uk': 'gb',
    'jp': 'jp',
    'kr': 'kr',
    'cn': 'cn',
    'hk': 'hk',
    'tw': 'tw',
    'pl': 'pl', 'cz': 'cz', 'sk': 'sk',
    'nl': 'nl', 'be': 'be',
    'es': 'es', 'it': 'it', 'pt': 'pt',
    'gr': 'gr', 'fi': 'fi', 'se': 'se', 'no': 'no', 'dk': 'dk',
    'au': 'au', 'nz': 'nz',
    'ca': 'ca',
    'br': 'br',
    'in': 'in',
    'tr': 'tr',
    'id': 'id', 'my': 'my', 'sg': 'sg',
    'ph': 'ph', 'th': 'th', 'vn': 'vn',
    'eg': 'eg', 'za': 'za', 'ng': 'ng',
    'il': 'il', 'sa': 'sa', 'ae': 'ae', 'ir': 'ir',
    'ar': 'ar', 'mx': 'mx',
    'bg': 'bg', 'ro': 'ro', 'rs': 'rs', 'hr': 'hr',
    'hu': 'hu', 'lt': 'lt', 'lv': 'lv',
    'lk': 'lk', 'bd': 'bd', 'pk': 'pk',
    'ma': 'ma', 'tn': 'tn', 'dz': 'dz',
    'mk': 'mk', 'ie': 'ie', 'lu': 'lu',
    'al': 'al', 'ba': 'ba',
}

# ── Category: engine → tag ────────────────────────────────────────────────────
ENGINE_CATEGORY = {
    'XenForo': 'forum',
    'phpBB': 'forum',
    'phpBB/Search': 'forum',
    'phpBB2/Search': 'forum',
    'vBulletin': 'forum',
    'Discourse': 'forum',
    'Flarum': 'forum',
    'MyBB': 'forum',
    'Wordpress/Author': 'blog',
    'op.gg': 'gaming',
}

# ── Category: URL/name keyword → tag (ordered, first match wins) ──────────────
URL_KEYWORDS = [
    (['forum', 'phpbb', 'vbulletin', 'mybb', 'xenforo', 'ipboard', 'ixbb',
      'board', 'bbs', 'discuss', 'talk', 'community'], 'forum'),
    (['blog', 'wordpress', 'livejournal', 'blogspot', 'tumblr'], 'blog'),
    (['anime', 'manga', 'otaku', 'cosplay'], 'anime'),
    (['music', 'audio', 'sound', 'bands', 'metal', 'rock', 'hip', 'jazz', 'radio'], 'music'),
    (['photo', 'photography', 'gallery', 'pics', 'flickr', 'imgur', 'instagram'], 'photo'),
    (['video', 'tube', 'vimeo', 'twitch', 'film', 'cinema', 'movie'], 'video'),
    (['game', 'gaming', 'minecraft', 'steam', 'roblox', 'warcraft', 'league', 'dota',
      'fifa', 'gamer', 'esport', 'playstation', 'xbox', 'nintendo'], 'gaming'),
    (['crypto', 'bitcoin', 'ethereum', 'blockchain', 'nft', 'defi', 'coin'], 'crypto'),
    (['torrent', 'tracker', 'seed', 'pirate', 'rutracker'], 'torrent'),
    (['wiki', 'wikia', 'fandom', 'encyclopedia'], 'wiki'),
    (['travel', 'trip', 'hotel', 'tour', 'flight', 'booking', 'hostel'], 'travel'),
    (['auto', 'car', 'drive', 'motor', 'wheel', 'moto', 'bike', 'avto'], 'auto'),
    (['sport', 'football', 'soccer', 'basket', 'hockey', 'tennis', 'chess',
      'fitness', 'gym', 'weight'], 'sport'),
    (['art', 'deviantart', 'artstation', 'draw', 'paint', 'illustr'], 'art'),
    (['design', 'creative', 'graphic', 'ui', 'ux'], 'design'),
    (['fashion', 'style', 'dress', 'beauty', 'makeup', 'cosmetic', 'beauty'], 'fashion'),
    (['science', 'research', 'academic', 'university', 'scholar', 'arxiv', 'journal'], 'science'),
    (['medic', 'health', 'doctor', 'pharma', 'hospital', 'clinic', 'dental'], 'medicine'),
    (['book', 'novel', 'fiction', 'literat', 'librar', 'read', 'story'], 'books'),
    (['mastodon', 'fediverse', 'activitypub', 'pixelfed'], 'mastodon'),
    (['lemmy'], 'lemmy'),
    (['chat', 'messenger', 'irc', 'jabber'], 'messaging'),
    (['news', 'press', 'media', 'daily', 'journal', 'gazette'], 'news'),
    (['shop', 'store', 'market', 'buy', 'sell', 'commerce', 'ebay', 'amazon', 'mall'], 'shopping'),
    (['finance', 'banking', 'invest', 'fund', 'money', 'financ', 'credit', 'loan'], 'finance'),
    (['trade', 'trading', 'forex', 'stock', 'broker', 'option'], 'trading'),
    (['code', 'coding', 'programming', 'developer', 'software', 'hack', 'pentest',
      'security', 'cyber', 'infosec', 'exploit'], 'coding'),
    (['tech', 'technology', 'hardware', 'computer', 'gadget', 'electro', 'digital'], 'tech'),
    (['network', 'friend', 'connect'], 'social'),
    (['hobby', 'diy', 'craft', 'collect', 'garden', 'breed', 'pet', 'model'], 'hobby'),
    (['freelance', 'gig', 'upwork', 'fiverr'], 'freelance'),
    (['job', 'career', 'recruit', 'employ', 'resume', 'vacancy', 'hr'], 'career'),
    (['sex', 'porn', 'adult', 'erotic', 'xxx', 'nude', 'nsfw', 'escort'], 'porn'),
    (['dating', 'love', 'hookup', 'single', 'match', 'date'], 'dating'),
    (['share', 'sharing', 'upload', 'file'], 'sharing'),
    (['3d', 'render', 'cgi', 'animation', 'blender', 'maya', 'cad', 'sketchup'], '3d'),
    (['stream', 'twitch', 'kick', 'dlive', 'rumble'], 'streaming'),
    (['military', 'army', 'navy', 'defense', 'war', 'weapon', 'airforce'], 'military'),
    (['professional', 'linkedin', 'business', 'entrepren', 'startup', 'corporate'], 'professional'),
    (['map', 'geo', 'location', 'place', 'gps', 'navigation'], 'maps'),
    (['link', 'bookmark', 'pinboard', 'pocket', 'instapaper'], 'links'),
    (['task', 'todo', 'project', 'manage', 'trello', 'asana', 'notion'], 'tasks'),
    (['document', 'pdf', 'office', 'spreadsheet', 'google doc'], 'documents'),
    (['tor', 'onion', 'darknet', 'dark web'], 'tor'),
    (['i2p', 'freenet', 'zeronet'], 'i2p'),
]

OFFICIAL_TAGS = set([
    '3d','anime','apps','archive','art','auto','blog','bookmarks','books','business',
    'career','classified','coding','crypto','cybercriminal','dating','design','discussion',
    'documents','education','erotic','fashion','finance','fintech','forum','freelance',
    'gambling','gaming','geosocial','hacking','hobby','i2p','lemmy','links','llm','maps',
    'mastodon','medicine','messaging','military','movies','music','networking','news','nft',
    'photo','porn','professional','q&a','reading','research','review','science','sharing',
    'shopping','social','sport','stock','streaming','tasks','tech','tor','torrent','trading',
    'travel','video','webcam','wiki','writing',
])

def is_region_tag(t):
    return bool(re.match(r'^[a-zA-Z]{2}$', t)) or t == 'global'

def get_tld(url):
    try:
        host = urlparse(url).hostname or ''
        parts = host.lower().split('.')
        if len(parts) >= 2:
            # Handle co.uk, com.au, etc.
            if len(parts) >= 3 and parts[-2] in ('co', 'com', 'net', 'org', 'gov', 'edu'):
                return parts[-1]
            return parts[-1]
        return ''
    except:
        return ''

def infer_region(name, url, existing_tags):
    tld = get_tld(url)
    region = TLD_REGION.get(tld)
    # Also check name for known region signals
    if not region:
        name_l = (name + ' ' + url).lower()
        if any(x in name_l for x in ['.ru/', 'ucoz.ru', 'forum.ru', 'mybb.ru']):
            region = 'ru'
    return region

def infer_category(name, url, engine, existing_tags):
    # Engine takes priority
    if engine and engine in ENGINE_CATEGORY:
        return ENGINE_CATEGORY[engine]
    # URL + name keyword check — use word-boundary to avoid 'cad' in 'cadaver'
    text = (name + ' ' + url).lower()
    for keywords, tag in URL_KEYWORDS:
        if any(re.search(r'\b' + re.escape(kw) + r'\b', text) for kw in keywords):
            if tag in OFFICIAL_TAGS:
                return tag
    return None

def process_data(data):
    sites = data['sites']
    changes = Counter()

    for name, s in sites.items():
        existing = s.get('tags', [])
        existing_set = set(existing)
        has_region = any(is_region_tag(t) for t in existing_set)
        has_category = bool(existing_set & OFFICIAL_TAGS)

        url = s.get('urlMain', s.get('url', ''))
        engine = s.get('engine')

        new_tags = list(existing)

        if not has_region:
            region = infer_region(name, url, existing_set)
            if region:
                new_tags.append(region)
                changes['region_added'] += 1
            else:
                changes['region_unknown'] += 1

        if not has_category:
            cat = infer_category(name, url, engine, existing_set)
            if cat:
                new_tags.append(cat)
                changes['category_added'] += 1
            else:
                changes['category_unknown'] += 1

        if set(new_tags) != existing_set:
            s['tags'] = new_tags

    return changes

if __name__ == '__main__':
    with open('maigret/resources/data.json') as f:
        data = json.load(f)

    changes = process_data(data)
    print("Changes summary:", dict(changes))

    # Preview: show 10 examples of what changed
    print("\nSample changes:")
    count = 0
    with open('maigret/resources/data.json') as f:
        orig = json.load(f)
    for name in list(data['sites'].keys())[:5000]:
        if name not in orig['sites']:
            continue
        old = orig['sites'][name].get('tags', [])
        new = data['sites'][name].get('tags', [])
        if set(old) != set(new):
            added = set(new) - set(old)
            print(f"  {name}: +{sorted(added)} (was: {sorted(old)})")
            count += 1
            if count >= 15:
                break

    # Write
    with open('maigret/resources/data.json', 'w') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print("\nWritten.")
