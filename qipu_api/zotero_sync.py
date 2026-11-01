from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from .models import BibliographicRecord, QipSource, SourceDating, ZoteroItemLink
from .zotero_formats import date_text, names, normalize_csl, publication_bounds


def source_csl(source):
    record = getattr(source, 'bibliography', None)
    data = dict(record.csl) if record else {'type': 'document'}
    data['title'] = source.title
    author = source.author_label.strip()
    if author and names(data) != author:
        data['author'] = [{'literal': author}]
    if not author:
        data.pop('author', None)
    dating = source.datings.filter(date_kind='publication').first()
    if dating and dating.date_text and dating.date_text != date_text(data.get('issued')):
        data['issued'] = {'raw': dating.date_text}
    return normalize_csl(data)


@transaction.atomic
def update_source(source, csl, *, overwrite):
    csl = normalize_csl(csl)
    previous = getattr(source, 'bibliography', None)
    previous_date = date_text(previous.csl.get('issued')) if previous else ''
    if overwrite:
        source.title = csl['title']
        source.author_label = names(csl)
        source.save(update_fields=['title', 'author_label', 'updated_at'])
    record, _ = BibliographicRecord.objects.get_or_create(source=source, defaults={'csl': csl})
    if overwrite:
        record.csl = csl
        record.save(update_fields=['csl', 'updated_at'])
    new_date = date_text(csl.get('issued'))
    new_bounds = publication_bounds(csl.get('issued')) or {}
    if overwrite and new_date:
        publication = source.datings.filter(date_kind='publication').first()
        if not publication:
            SourceDating.objects.create(source=source, date_kind='publication', date_text=new_date,
                                        is_primary=not source.datings.exists(), **new_bounds)
        elif previous_date and publication.date_text == previous_date:
            old_bounds = publication_bounds(previous.csl.get('issued')) or {}
            keys = ('begin_of_begin', 'end_of_begin', 'begin_of_end', 'end_of_end')
            if all(getattr(publication, key) == old_bounds.get(key) for key in keys) and not any(
                    getattr(publication, f'{key}_time') for key in keys):
                publication.date_text = new_date
                for key in keys:
                    setattr(publication, key, new_bounds.get(key))
                publication.save(update_fields=['date_text', *keys])
    return source


def create_source(project, user, csl):
    csl = normalize_csl(csl)
    source = QipSource.objects.create(project=project, created_by=user, title=csl['title'],
        author_label=names(csl), description=csl.get('abstract', '')[:10000])
    return update_source(source, csl, overwrite=True)


def candidates(project, csl):
    """Suggest, never merge automatically. Identity keys have priority over fuzzy titles."""
    doi = csl.get('DOI', '').strip()
    isbn = csl.get('ISBN', '').strip()
    condition = Q(title__iexact=csl['title'])
    if doi: condition |= Q(bibliography__csl__DOI__iexact=doi)
    if isbn: condition |= Q(bibliography__csl__ISBN__iexact=isbn)
    choices = []
    for source in QipSource.objects.filter(project=project).filter(condition).select_related('bibliography').distinct()[:20]:
        other = source_csl(source)
        same_identifier = (doi and other.get('DOI', '').casefold() == doi.casefold()) or (
            isbn and other.get('ISBN', '').casefold() == isbn.casefold())
        same_title = source.title.strip().casefold() == csl['title'].casefold()
        if same_identifier or same_title:
            choices.append({'id': source.pk, 'title': source.title, 'reason': 'identifier' if same_identifier else 'title',
                            'updated_at': source.updated_at.isoformat()})
    return choices[:20]


def verify_source(project, row, source_id):
    source = QipSource.objects.filter(project=project, pk=source_id).first()
    if not source:
        raise ValidationError({'source': 'Source outside the project or missing.'})
    if source_id == row.get('source_id') and row.get('source_updated') and source.updated_at.isoformat() != row['source_updated']:
        raise ValidationError({'source': 'Source changed since preview. Prepare a new comparison.'})
    candidate = next((entry for entry in row.get('candidates', []) if entry['id'] == source.id), None)
    if row['id'].startswith('file:') and (not candidate or candidate['updated_at'] != source.updated_at.isoformat()):
        raise ValidationError({'source': 'Choose an unchanged suggested source or prepare a new comparison.'})
    return source


def link_item(source, collection, key, version, csl):
    if ZoteroItemLink.objects.filter(collection=collection, item_key=key).exclude(source=source).exists():
        raise ValidationError({'zotero': 'This Zotero item is already linked to another source.'})
    if ZoteroItemLink.objects.filter(source=source).exclude(collection=collection, item_key=key).exists():
        raise ValidationError({'source': 'This source is already linked to another Zotero item.'})
    ZoteroItemLink.objects.update_or_create(source=source, defaults={
        'collection': collection, 'item_key': key, 'item_version': version,
        'last_synced': normalize_csl(csl),
    })
