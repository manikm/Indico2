from indico.core.db import db

class ContributionLimit(db.Model):
    __tablename__ = 'contribution_limits'
    __table_args__ = (db.UniqueConstraint('event_id', 'track_id', 'type_id'),
                      {'schema': 'events'})

    id = db.Column(
        db.Integer,
        primary_key=True
    )
    event_id = db.Column(
        db.Integer,
        db.ForeignKey('events.events.id'),
        index=True,
        nullable=False
    )
    track_id = db.Column(
        db.Integer,
        db.ForeignKey('events.tracks.id', ondelete='SET NULL'),
        index=True,
        nullable=True
    )
    type_id = db.Column(
        db.Integer,
        db.ForeignKey('events.contribution_types.id', ondelete='SET NULL'),
        index=True,
        nullable=True
    )
    value = db.Column(
        db.Integer,
        nullable=True
    )
    event = db.relationship(
        'Event',
        lazy=True,
        backref=db.backref(
            'contribution_limits',
            cascade='all, delete-orphan',
            lazy='dynamic'
        )
    )
    track = db.relationship(
        'Track',
        lazy=True,
        backref=db.backref(
            'contribution_limits',
            cascade='all, delete-orphan',
            lazy='dynamic'
        )
    )
    type = db.relationship(
        'ContributionType',
        lazy=True,
        backref=db.backref(
            'contribution_limits',
            cascade='all, delete-orphan',
            lazy='dynamic'
        )
    )