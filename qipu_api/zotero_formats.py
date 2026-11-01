"""Conservative bibliographic mapping: a date string is never a historical instant."""
import json
import re
import calendar
from datetime import date
from urllib.parse import urlsplit

from rest_framework.exceptions import ValidationError


CSL_FIELDS = ('type', 'title', 'author', 'editor', 'issued', 'container-title', 'publisher',
              'DOI', 'ISBN', 'URL', 'abstract', 'language', 'volume', 'issue', 'page',
              'id', 'accessed', 'ISSN', 'journalAbbreviation', 'title-short', 'source',
              'license', 'collection-title', 'edition', 'contributor')
ZOTERO_TYPES = {'article-journal': 'journalArticle', 'article-newspaper': 'newspaperArticle',
                'article-magazine': 'magazineArticle', 'chapter': 'bookSection', 'webpage': 'webpage',
                'thesis': 'thesis', 'report': 'report', 'book': 'book', 'document': 'document'}
CSL_TYPES = {value: key for key, value in ZOTERO_TYPES.items()}
RIS_TYPES = {'JOUR': 'article-journal', 'NEWS': 'article-newspaper', 'CHAP': 'chapter',
             'BOOK': 'book', 'THES': 'thesis', 'RPRT': 'report', 'ELEC': 'webpage'}
CSL_RIS_TYPES = {value: key for key, value in RIS_TYPES.items()}


def date_text(value):
    if isinstance(value, str):
        return value.strip()[:250]
    if isinstance(value, dict):
        if isinstance(value.get('raw'), str):
            return value['raw'].strip()[:250]
        parts = value.get('date-parts', [])
        if parts and isinstance(parts[0], list):
            return '-'.join(str(part).zfill(2) if index else str(part)
                            for index, part in enumerate(parts[0]))[:250]
    return ''


def publication_bounds(value):
    """Only ISO calendar dates with explicit precision yield a historical interval."""
    if isinstance(value, dict) and isinstance(value.get('raw'), str) and value['raw'].strip():
        value = value['raw'].strip()
    elif isinstance(value, dict):
        parts = value.get('date-parts')
        value = parts[0] if isinstance(parts, list) and parts and isinstance(parts[0], list) else None
    if isinstance(value, str):
        match = re.fullmatch(r'(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?', value)
        if not match:
            return None
        value = [int(part) for part in match.groups() if part is not None]
    if not isinstance(value, list) or not 1 <= len(value) <= 3 or any(
            isinstance(part, bool) or not isinstance(part, (int, str)) or
            not str(part).isdigit() for part in value):
        return None
    year, *rest = [int(part) for part in value]
    if not 1 <= year <= 9999:
        return None
    month = rest[0] if rest else 1
    day = rest[1] if len(rest) > 1 else 1
    try:
        start = date(year, month, day)
        end = date(year, month if rest else 12,
                   day if len(rest) > 1 else calendar.monthrange(year, month if rest else 12)[1])
    except ValueError:
        return None
    return {'begin_of_begin': start, 'end_of_end': end}


def normalize_csl(item, with_warnings=False):
    if not isinstance(item, dict):
        raise ValidationError({'file': 'Each reference must be an object.'})
    title = item.get('title')
    if not isinstance(title, str) or not title.strip():
        raise ValidationError({'title': 'A non-empty title is required.'})
    warnings = []
    title = title.strip()
    if len(title) > 2000:
        title = title[:2000]
        warnings.append('title (truncated to 2000 characters)')
    data = {key: item[key] for key in CSL_FIELDS if key in item and item[key] not in (None, '', [], {})}
    data['title'] = title
    for field in ('type', 'container-title', 'publisher', 'DOI', 'ISBN', 'URL', 'abstract',
                   'language', 'volume', 'issue', 'page', 'id', 'ISSN', 'journalAbbreviation',
                   'title-short', 'source', 'license', 'collection-title', 'edition'):
        if field in data and not isinstance(data[field], str):
            data.pop(field)
            warnings.append(field)
        elif field in data and len(data[field]) > 10000:
            data[field] = data[field][:10000]
            warnings.append(f'{field} (truncated to 10000 characters)')
    if data.get('URL'):
        candidate = data['URL'].strip()
        parsed = urlsplit(candidate)
        if not parsed.scheme and candidate and not any(char.isspace() for char in candidate):
            candidate = 'https://' + candidate
            parsed = urlsplit(candidate)
            warnings.append('URL (https added)')
        if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
            data.pop('URL')
            warnings.append('URL')
        else:
            data['URL'] = candidate
    for field in ('issued', 'accessed'):
        if field in data:
            original = data[field]
            formatted = date_text(original)
            if not formatted:
                del data[field]
                warnings.append(field)
            elif isinstance(original, dict) and publication_bounds(original) and not original.get('raw'):
                data[field] = {'date-parts': original['date-parts']}
                if original.get('season'):
                    data[field]['season'] = original['season']
            else:
                data[field] = {'raw': formatted}
    for key in ('author', 'editor', 'contributor'):
        creators = data.get(key, [])
        if not isinstance(creators, list):
            data.pop(key, None)
            warnings.append(key)
            continue
        normalized = []
        for row in creators:
            if not isinstance(row, dict):
                warnings.append(key)
                continue
            person = {name: value[:1000] for name, value in row.items() if isinstance(value, str) and value.strip()}
            if person:
                normalized.append(person)
            elif row:
                warnings.append(key)
        if normalized:
            data[key] = normalized
        else:
            data.pop(key, None)
    if len(json.dumps(data, ensure_ascii=False)) > 200000:
        raise ValidationError({'file': 'Reference exceeds 200 KB.'})
    return (data, warnings) if with_warnings else data


def names(csl):
    return ', '.join((row.get('literal') or ' '.join(filter(None, (row.get('given'), row.get('family')))))
                     for row in csl.get('author', []) if isinstance(row, dict))[:250]


def parse_csl_json(raw, with_warnings=False):
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValidationError({'file': 'Invalid CSL JSON.'})
    if isinstance(data, dict) and isinstance(data.get('items'), list):
        data = data['items']
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) > 2000:
        raise ValidationError({'file': 'Expected an array of at most 2000 CSL JSON references.'})
    parsed = []
    for row in data:
        try:
            parsed.append(normalize_csl(row, with_warnings=True))
        except ValidationError:
            if not with_warnings:
                raise
            parsed.append((None, ['title']))
    if with_warnings:
        return [(csl, sorted(set(row) - set(CSL_FIELDS)) + warnings) for (csl, warnings), row in zip(parsed, data)]
    return [csl for csl, _ in parsed]


def parse_ris(raw, with_warnings=False):
    try:
        text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        raise ValidationError({'file': 'RIS must be UTF-8.'})
    items, tags = [], {}
    for line in text.splitlines():
        match = re.match(r'^([A-Z][A-Z0-9])  -\s?(.*)$', line)
        if match:
            key, value = match.groups()
            if key == 'TY' and tags:
                items.append(tags); tags = {}
            if key == 'ER':
                if tags: items.append(tags)
                tags = {}
            else:
                tags.setdefault(key, []).append(value.strip())
        elif tags and line.strip():
            key = next(reversed(tags))
            tags[key][-1] += '\n' + line.strip()
    if tags: items.append(tags)
    if len(items) > 2000:
        raise ValidationError({'file': 'At most 2000 RIS references per file.'})
    result, warnings = [], []
    known_tags = {'TY', 'TI', 'T1', 'CT', 'AU', 'A1', 'PY', 'Y1', 'DA', 'JO', 'JF', 'T2', 'PB',
                  'DO', 'SN', 'UR', 'AB', 'VL', 'IS', 'SP'}
    for item in items:
        warnings.append(sorted(set(item) - known_tags))
        first = lambda key: (item.get(key) or [''])[0]
        creators = []
        for author in item.get('AU', []) + item.get('A1', []):
            parts = [part.strip() for part in author.split(',', 1)]
            creators.append({'family': parts[0], 'given': parts[1]} if len(parts) > 1 else {'literal': author})
        try:
            csl, normalized_warnings = normalize_csl({'type': RIS_TYPES.get(first('TY'), 'document'),
                'title': first('TI') or first('T1') or first('CT'), 'author': creators,
                'issued': {'raw': first('PY') or first('Y1') or first('DA')},
                'container-title': first('JO') or first('JF') or first('T2'), 'publisher': first('PB'),
                'DOI': first('DO'), 'ISBN': first('SN'), 'URL': first('UR'), 'abstract': first('AB'),
                'volume': first('VL'), 'issue': first('IS'), 'page': first('SP')}, with_warnings=True)
        except ValidationError:
            if not with_warnings:
                raise
            csl, normalized_warnings = None, ['title']
        result.append(csl)
        warnings[-1].extend(normalized_warnings)
    return list(zip(result, warnings)) if with_warnings else result


def export_ris(items):
    output = []
    for item in items:
        csl = normalize_csl(item)
        output.append(f"TY  - {CSL_RIS_TYPES.get(csl.get('type'), 'GEN')}")
        for field, tag in [('title', 'TI'), ('container-title', 'JO'), ('publisher', 'PB'),
                           ('DOI', 'DO'), ('ISBN', 'SN'), ('URL', 'UR'), ('abstract', 'AB'),
                           ('volume', 'VL'), ('issue', 'IS'), ('page', 'SP')]:
            if isinstance(csl.get(field), str) and csl[field]:
                output.append(f"{tag}  - {csl[field].replace(chr(10), ' ')}")
        for creator in csl.get('author', []):
            name = (creator.get('literal') or ', '.join(filter(None, (creator.get('family'), creator.get('given')))))
            if name: output.append(f'AU  - {name}')
        if date_text(csl.get('issued')): output.append(f"PY  - {date_text(csl['issued'])}")
        output.extend(['ER  - ', ''])
    return '\r\n'.join(output)


def from_zotero(data):
    creators = {}
    for creator in data.get('creators', []):
        category = creator.get('creatorType')
        if category in ('author', 'editor'):
            creators.setdefault(category, []).append({key: creator[key] for key in ('firstName', 'lastName', 'name') if key in creator})
    def convert(rows):
        return [{'literal': row['name']} if row.get('name') else
                {'given': row.get('firstName', ''), 'family': row.get('lastName', '')} for row in rows]
    return normalize_csl({'type': CSL_TYPES.get(data.get('itemType'), 'document'), 'title': data.get('title', ''),
        'author': convert(creators.get('author', [])), 'editor': convert(creators.get('editor', [])),
        'issued': {'raw': data.get('date', '')},
        'container-title': data.get('publicationTitle') or data.get('bookTitle', ''),
        'publisher': data.get('publisher') or data.get('university') or data.get('institution', ''),
        'DOI': data.get('DOI', ''), 'ISBN': data.get('ISBN', ''),
        'URL': data.get('url', ''), 'abstract': data.get('abstractNote', ''),
        'language': data.get('language', ''), 'volume': data.get('volume', ''),
        'issue': data.get('issue', ''), 'page': data.get('pages', '')})


def to_zotero(csl):
    csl = normalize_csl(csl)
    item_type = ZOTERO_TYPES.get(csl.get('type'), 'document')
    result = {'itemType': item_type, 'title': csl['title']}
    common = [('DOI', 'DOI'), ('URL', 'url'), ('abstract', 'abstractNote'), ('language', 'language')]
    by_type = {
        'book': [('publisher', 'publisher'), ('ISBN', 'ISBN')],
        'journalArticle': [('container-title', 'publicationTitle'), ('volume', 'volume'),
                           ('issue', 'issue'), ('page', 'pages')],
        'newspaperArticle': [('container-title', 'publicationTitle'), ('page', 'pages')],
        'magazineArticle': [('container-title', 'publicationTitle'), ('volume', 'volume'),
                            ('issue', 'issue'), ('page', 'pages')],
        'bookSection': [('container-title', 'bookTitle'), ('publisher', 'publisher'), ('page', 'pages')],
        'thesis': [('publisher', 'university')],
        'report': [('publisher', 'institution')],
    }
    for field, target in common + by_type.get(item_type, []):
        if csl.get(field): result[target] = csl[field]
    if date_text(csl.get('issued')): result['date'] = date_text(csl['issued'])
    result['creators'] = [{**({'name': row['literal']} if row.get('literal') else
                            {'firstName': row.get('given', ''), 'lastName': row.get('family', '')}),
                           'creatorType': category} for category in ('author', 'editor') if category == 'author' or item_type in (
                               'book', 'bookSection', 'report') for row in csl.get(category, [])]
    return result


def zotero_warnings(csl):
    csl = normalize_csl(csl)
    converted = to_zotero(csl)
    destinations = {'container-title': ('publicationTitle', 'bookTitle'), 'publisher': ('publisher', 'university', 'institution'),
                    'DOI': ('DOI',), 'ISBN': ('ISBN',), 'URL': ('url',), 'abstract': ('abstractNote',),
                    'language': ('language',), 'volume': ('volume',), 'issue': ('issue',), 'page': ('pages',)}
    warnings = [field for field, targets in destinations.items() if csl.get(field) and not any(
        target in converted for target in targets)]
    if csl.get('editor') and not any(row['creatorType'] == 'editor' for row in converted['creators']):
        warnings.append('editor')
    if csl.get('type') not in ZOTERO_TYPES:
        warnings.append('type')
    warnings.extend(field for field in ('id', 'accessed', 'ISSN', 'journalAbbreviation',
        'title-short', 'source', 'license', 'collection-title', 'edition', 'contributor') if csl.get(field))
    return warnings


def ris_warnings(csl):
    csl = normalize_csl(csl)
    warnings = [field for field in ('id', 'editor', 'contributor', 'language', 'accessed', 'ISSN',
        'journalAbbreviation', 'title-short', 'source', 'license', 'collection-title', 'edition') if csl.get(field)]
    if csl.get('type') not in CSL_RIS_TYPES:
        warnings.append('type')
    return warnings


def zotero_import_warnings(data):
    mapped = {'itemType', 'title', 'creators', 'date', 'publicationTitle', 'bookTitle', 'publisher',
              'university', 'institution', 'DOI', 'ISBN', 'url', 'abstractNote', 'language',
              'volume', 'issue', 'pages', 'collections', 'dateAdded', 'dateModified', 'key', 'version'}
    warnings = sorted(key for key, value in data.items() if key not in mapped and value not in (None, '', [], {}))
    if data.get('itemType') not in CSL_TYPES:
        warnings.append('itemType')
    return warnings
