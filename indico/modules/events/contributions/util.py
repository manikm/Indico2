# This file is part of Indico.
# Copyright (C) 2002 - 2017 European Organization for Nuclear Research (CERN).
#
# Indico is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.
#
# Indico is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Indico; if not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals

from collections import defaultdict
from io import BytesIO
from operator import attrgetter

from sqlalchemy.orm import contains_eager, joinedload, load_only, noload

from indico.core.db import db
from indico.modules.attachments.util import get_attached_items
from indico.modules.events.contributions.models.contributions import Contribution
from indico.modules.events.contributions.models.persons import ContributionPersonLink, SubContributionPersonLink
from indico.modules.events.contributions.models.principals import ContributionPrincipal
from indico.modules.events.contributions.models.subcontributions import SubContribution
from indico.modules.events.models.events import Event
from indico.modules.events.models.persons import EventPerson
from indico.modules.events.util import serialize_person_link
from indico.util.date_time import format_datetime, format_human_timedelta
from indico.web.flask.templating import get_template_module
from indico.web.flask.util import url_for
from indico.web.http_api.metadata.serializer import Serializer
from indico.web.util import jsonify_data


def get_events_with_linked_contributions(user, dt=None):
    """Returns a dict with keys representing event_id and the values containing
    data about the user rights for contributions within the event

    :param user: A `User`
    :param dt: Only include events taking place on/after that date
    """
    def add_acl_data():
        query = (user.in_contribution_acls
                 .options(load_only('contribution_id', 'roles', 'full_access', 'read_access'))
                 .options(noload('*'))
                 .options(contains_eager(ContributionPrincipal.contribution).load_only('event_id'))
                 .join(Contribution)
                 .join(Event, Event.id == Contribution.event_id)
                 .filter(~Contribution.is_deleted, ~Event.is_deleted, Event.ends_after(dt)))
        for principal in query:
            roles = data[principal.contribution.event_id]
            if 'submit' in principal.roles:
                roles.add('contribution_submission')
            if principal.full_access:
                roles.add('contribution_manager')
            if principal.read_access:
                roles.add('contribution_access')

    def add_contrib_data():
        has_contrib = (EventPerson.contribution_links.any(
            ContributionPersonLink.contribution.has(~Contribution.is_deleted)))
        has_subcontrib = EventPerson.subcontribution_links.any(
            SubContributionPersonLink.subcontribution.has(db.and_(
                ~SubContribution.is_deleted,
                SubContribution.contribution.has(~Contribution.is_deleted))))
        query = (Event.query
                 .options(load_only('id'))
                 .options(noload('*'))
                 .filter(~Event.is_deleted,
                         Event.ends_after(dt),
                         Event.persons.any((EventPerson.user_id == user.id) & (has_contrib | has_subcontrib))))
        for event in query:
            data[event.id].add('contributor')

    data = defaultdict(set)
    add_acl_data()
    add_contrib_data()
    return data


def serialize_contribution_person_link(person_link, is_submitter=None):
    """Serialize ContributionPersonLink to JSON-like object"""
    data = serialize_person_link(person_link)
    data['isSpeaker'] = person_link.is_speaker
    if not isinstance(person_link, SubContributionPersonLink):
        data['authorType'] = person_link.author_type.value
        data['isSubmitter'] = person_link.is_submitter if is_submitter is None else is_submitter
    return data


def generate_spreadsheet_from_contributions(contributions):
    """Return a tuple consisting of spreadsheet columns and respective
    contribution values"""

    headers = ['Id', 'Title', 'Description', 'Date', 'Duration', 'Type', 'Session', 'Track', 'Presenters', 'Authors', 'Co-authors', 'Materials']
    rows = []
    for c in sorted(contributions, key=attrgetter('friendly_id')):
        contrib_data = {'Id': c.friendly_id, 'Title': c.title, 'Description': c.description,
                        'Duration': format_human_timedelta(c.duration),
                        'Date': c.timetable_entry.start_dt if c.timetable_entry else None,
                        'Type': c.type.name if c.type else None,
                        'Session': c.session.title if c.session else None,
                        'Track': c.track.title if c.track else None,
                        'Materials': None,
                        'Authors': ', '.join(speaker.person.full_name for speaker in c.primary_authors),
                        'Co-authors': ', '.join(speaker.person.full_name for speaker in c.secondary_authors),
                        'Presenters': ', '.join(speaker.person.full_name for speaker in c.speakers)}

        attachments = []
        attached_items = get_attached_items(c)
        for attachment in attached_items.get('files', []):
            attachments.append(attachment.absolute_download_url)

        for folder in attached_items.get('folders', []):
            for attachment in folder.attachments:
                attachments.append(attachment.absolute_download_url)

        if attachments:
            contrib_data['Materials'] = ', '.join(attachments)
        rows.append(contrib_data)
    return headers, rows


def make_contribution_form(event):
    """Extends the contribution WTForm to add the extra fields.

    Each extra field will use a field named ``custom_ID``.

    :param event: The `Event` for which to create the contribution form.
    :return: A `ContributionForm` subclass.
    """
    from indico.modules.events.contributions.forms import ContributionForm

    form_class = type(b'_ContributionForm', (ContributionForm,), {})
    for custom_field in event.contribution_fields:
        field_impl = custom_field.mgmt_field
        if field_impl is None:
            # field definition is not available anymore
            continue
        name = 'custom_{}'.format(custom_field.id)
        setattr(form_class, name, field_impl.create_wtf_field())
    return form_class


def contribution_type_row(contrib_type):
    template = get_template_module('events/contributions/management/_types_table.html')
    html = template.types_table_row(contrib_type=contrib_type)
    return jsonify_data(html_row=html, flash=False)


def _query_contributions_with_user_as_submitter(event, user):
    return (Contribution.query.with_parent(event)
            .filter(Contribution.acl_entries.any(db.and_(ContributionPrincipal.has_management_role('submit'),
                                                         ContributionPrincipal.user == user))))


def get_contributions_with_user_as_submitter(event, user):
    """Get a list of contributions in which the `user` has submission rights"""
    return (_query_contributions_with_user_as_submitter(event, user)
            .options(joinedload('acl_entries'))
            .order_by(db.func.lower(Contribution.title))
            .all())


def has_contributions_with_user_as_submitter(event, user):
    return _query_contributions_with_user_as_submitter(event, user).has_rows()


def serialize_contribution_for_ical(contrib):
    return {
        '_fossil': 'contributionMetadata',
        'id': contrib.id,
        'startDate': contrib.timetable_entry.start_dt if contrib.timetable_entry else None,
        'endDate': contrib.timetable_entry.end_dt if contrib.timetable_entry else None,
        'url': url_for('contributions.display_contribution', contrib, _external=True),
        'title': contrib.title,
        'location': contrib.venue_name,
        'roomFullname': contrib.room_name,
        'speakers': [serialize_person_link(x) for x in contrib.speakers],
        'description': contrib.description
    }


def get_contribution_ical_file(contrib):
    data = {'results': serialize_contribution_for_ical(contrib)}
    serializer = Serializer.create('ics')
    return BytesIO(serializer(data))
