#!/usr/bin/python
# -*- coding: iso-8859-15 -*-
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

import re, codecs, hmac, hashlib
from datetime import datetime, timedelta

from flask import flash, redirect, request, session
from sqlalchemy.orm import defaultload

from indico.modules.events.registration.models.forms import RegistrationForm
from indico.modules.events.registration.util import get_event_section_data, make_registration_form, modify_registration
from indico.util.string import camelize_keys


class RegistrationFormMixin:
    """Mixin for single registration form RH"""

    normalize_url_spec = {
        'locators': {
            lambda self: self.regform
        }
    }

    def _process_args(self):
        self.regform = (RegistrationForm.query
                        .filter_by(id=request.view_args['reg_form_id'], is_deleted=False)
                        .options(defaultload('form_items').joinedload('children').joinedload('current_data'))
                        .one())


class RegistrationEditMixin:
    def _process(self):
        form = make_registration_form(self.regform, management=self.management, registration=self.registration)()

        verif_field, reg_field = ('','')
        for k in form._fields:
            if form._fields[k].label.text.lower() == 'registration option':
                reg_field = form._fields[k].label.field_id
            if form._fields[k].label.text.lower() == 'verification code':
                verif_field = form._fields[k].label.field_id

        verif_code = ''
        if verif_field and form._fields[verif_field].data:
            verif_code = form._fields[verif_field].data
        elif request.form.get(verif_field):
            verif_code = request.form.get(verif_field)

        reg_opt = ''
        if reg_field and form._fields[reg_field].data:
            reg_opt = form._fields[reg_field].data

        opt_text = ''
        if reg_opt:
            for i in self.regform.active_fields:
                if i.title.lower() == 'registration option':
                    for k in i.data['captions']:
                        if k == next(iter(reg_opt)):
                            opt_text = i.data['captions'][k]
                else:
                    continue

        members_choice = False
        if opt_text and re.search(r' members', opt_text, flags=re.IGNORECASE):
            members_choice = True

        registration_data = {r.field_data.field.html_field_name: camelize_keys(r.user_data)
                             for r in self.registration.data}

        reg_allowed = False
        if members_choice:
            str_list = [registration_data['first_name']+registration_data['last_name']+'/'+str(self.event.id)+'/'+datetime.today().strftime('%Y-%m-%d'),
                    registration_data['first_name']+registration_data['last_name']+'/'+str(self.event.id)+'/'+(datetime.now() + timedelta(days=-1)).strftime('%Y-%m-%d'),
                    registration_data['first_name']+registration_data['last_name']+'/'+str(self.event.id)+'/'+(datetime.now() + timedelta(days=-2)).strftime('%Y-%m-%d')]
            for strn in str_list:
                sha = hmac.new(u''.encode(), strn.lower().encode('utf-8'), hashlib.sha256).hexdigest()
                md = hmac.new(''.encode(), sha.encode(), hashlib.md5).hexdigest()
                enc = codecs.encode(codecs.decode(md, 'hex'), 'base64').decode().replace("\n","").replace("=","").replace("/","9").replace("+","8")
                print(strn.lower())
                print(enc)
                if enc == verif_code:
                    reg_allowed = True

        setattr(self.regform, 'member_attempt', False)
        if (members_choice and reg_allowed) or not members_choice:
            if form.validate_on_submit():
                data = form.data
                notify_user = not self.management or data.pop('notify_user', False)
                if self.management:
                    session['registration_notify_user_default'] = notify_user
                modify_registration(self.registration, data, management=self.management, notify_user=notify_user)
                return redirect(self.success_url)
            elif form.is_submitted():
                # not very pretty but usually this never happens thanks to client-side validation
                for error in form.error_list:
                    flash(error, 'error')
        else:
            setattr(self.regform, 'member_attempt', True)

        section_data = camelize_keys(get_event_section_data(self.regform, management=self.management,
                                                            registration=self.registration))

        registration_metadata = {
            'paid': self.registration.is_paid,
            'manager': self.management
        }

        return self.view_class.render_template(self.template_file, self.event,
                                               sections=section_data, regform=self.regform,
                                               registration_data=registration_data,
                                               registration_metadata=registration_metadata,
                                               registration=self.registration)
