from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Category(db.Model):
    """Tool categories with slugs and icons."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    icon = db.Column(db.String(50))
    description = db.Column(db.Text)
    tools = db.relationship("Tool", backref="category", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "icon": self.icon,
            "description": self.description,
            "tool_count": self.tools.count(),
        }


class Tool(db.Model):
    """Individual AI tool listing."""

    __tablename__ = "tools"
    __table_args__ = (
        db.Index("idx_tool_slug", "slug"),
        db.Index("idx_tool_category", "category_id"),
        db.Index("idx_tool_featured", "is_featured"),
        db.Index("idx_tool_approved", "is_approved"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    tagline = db.Column(db.String(300))
    description = db.Column(db.Text, nullable=False)
    features = db.Column(db.Text)  # JSON array stored as text
    pricing = db.Column(db.String(50))  # Free / Freemium / Paid / Enterprise
    pricing_details = db.Column(db.Text)
    website_url = db.Column(db.String(500))
    rating = db.Column(db.Float, default=0.0)
    review_count = db.Column(db.Integer, default=0)
    is_featured = db.Column(db.Boolean, default=False, index=True)
    is_approved = db.Column(db.Boolean, default=True, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def get_features(self):
        import json

        if self.features:
            try:
                return json.loads(self.features)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    # SQLAlchemy relationship attributes accessed via hybrid_property-style descriptors
    # type: ignore[misc]
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "tagline": self.tagline,
            "description": self.description,
            "features": self.get_features(),
            "pricing": self.pricing,
            "pricing_details": self.pricing_details,
            "website_url": self.website_url,
            "rating": self.rating,
            "review_count": self.review_count,
            "is_featured": self.is_featured,
            "category": self.category.to_dict() if self.category else None,  # type: ignore[union-attr]
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Favorite(db.Model):
    """Session-based favorites (no auth required)."""

    __tablename__ = "favorites"
    __table_args__ = (
        db.UniqueConstraint("tool_id", "session_id", name="uq_favorite_tool_session"),
        db.Index("idx_favorite_session", "session_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tool_id = db.Column(db.Integer, db.ForeignKey("tools.id"), nullable=False)
    session_id = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tool = db.relationship("Tool", backref="favorites")
