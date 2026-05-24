import os
import secrets
import re
import json
from datetime import datetime
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort,
    jsonify,
    make_response,
)
from models import db, Category, Tool, Favorite


# ─── Configuration ───────────────────────────────────────────────
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
    _basedir = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(_basedir, "instance", "ai_tools.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PER_PAGE = 12


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)

    # ─── Template Filters ────────────────────────────────────────
    @app.template_filter("star_rating")
    def star_rating_filter(rating):
        if not rating:
            return ""
        full = int(rating)
        half = 1 if rating - full >= 0.3 else 0
        empty = 5 - full - half
        html = '<i class="fa-solid fa-star"></i>' * full
        if half:
            html += '<i class="fa-solid fa-star-half-stroke"></i>'
        html += '<i class="fa-regular fa-star"></i>' * empty
        return html

    @app.template_filter("tool_color")
    def tool_color_filter(name):
        colors = [
            "#f59e0b",
            "#ef4444",
            "#22c55e",
            "#06b6d4",
            "#8b5cf6",
            "#ec4899",
            "#f97316",
            "#14b8a6",
            "#6366f1",
            "#84cc16",
            "#e11d48",
            "#0891b2",
            "#a855f7",
            "#ea580c",
            "#059669",
            "#7c3aed",
            "#db2777",
            "#0ea5e9",
            "#84cc16",
            "#f59e0b",
        ]
        h = sum(ord(c) for c in name.lower())
        return colors[h % len(colors)]

    @app.template_filter("truncate_words")
    def truncate_words(s, n=25):
        words = s.split()
        if len(words) <= n:
            return s
        return " ".join(words[:n]) + "..."

    @app.template_filter("time_ago")
    def time_ago(dt):
        if not dt:
            return ""
        now = datetime.utcnow()
        diff = now - dt
        if diff.days > 365:
            return f"{diff.days // 365}y ago"
        elif diff.days > 30:
            return f"{diff.days // 30}mo ago"
        elif diff.days > 0:
            return f"{diff.days}d ago"
        elif diff.seconds > 3600:
            return f"{diff.seconds // 3600}h ago"
        elif diff.seconds > 60:
            return f"{diff.seconds // 60}m ago"
        return "Just now"

    @app.context_processor
    def inject_globals():
        now = datetime.utcnow()
        return {
            "categories": Category.query.order_by(Category.name).all(),
            "csrf_token": session.get("csrf_token", ""),
            "now": now,
        }

    # ─── CSRF Protection ─────────────────────────────────────────
    @app.before_request
    def ensure_csrf():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)

    def check_csrf():
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not token or token != session.get("csrf_token"):
            abort(403)

    # ─── Error Handlers ──────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return render_template("base.html", error_404=True), 404

    @app.errorhandler(403)
    def forbidden(e):
        flash("Invalid request. Please try again.", "error")
        return redirect(url_for("index"))

    @app.errorhandler(500)
    def server_error(e):
        flash("Something went wrong. Please try again later.", "error")
        return redirect(url_for("index"))

    # ─── Helpers ─────────────────────────────────────────────────
    def get_session_id():
        if "session_id" not in session:
            session["session_id"] = secrets.token_hex(16)
            session.permanent = True
        return session["session_id"]

    def get_fav_count():
        sid = session.get("session_id")
        if not sid:
            return 0
        return Favorite.query.filter_by(session_id=sid).count()

    def get_avg_rating():
        result = (
            db.session.query(db.func.avg(Tool.rating))
            .filter_by(is_approved=True)
            .scalar()
        )
        return round(result, 1) if result else 4.5

    def is_tool_favorited(tool_id):
        sid = session.get("session_id")
        if not sid:
            return False
        return (
            Favorite.query.filter_by(tool_id=tool_id, session_id=sid).first()
            is not None
        )

    # ─── Routes ───────────────────────────────────────────────────

    @app.route("/")
    def index():
        featured = (
            Tool.query.filter_by(is_featured=True, is_approved=True)
            .order_by(Tool.rating.desc())
            .limit(6)
            .all()
        )

        recent = (
            Tool.query.filter_by(is_approved=True)
            .order_by(Tool.created_at.desc())
            .limit(4)
            .all()
        )

        top_rated = (
            Tool.query.filter_by(is_approved=True)
            .order_by(Tool.rating.desc())
            .limit(4)
            .all()
        )

        categories = Category.query.all()
        total_tools = Tool.query.filter_by(is_approved=True).count()
        total_categories = len(categories)
        avg_rating = get_avg_rating()

        return render_template(
            "index.html",
            featured=featured,
            recent=recent,
            top_rated=top_rated,
            categories=categories,
            total_tools=total_tools,
            total_categories=total_categories,
            avg_rating=avg_rating,
        )

    @app.route("/tools")
    def tools():
        query = Tool.query.filter_by(is_approved=True)

        q = request.args.get("q", "").strip()
        if q:
            query = query.filter(
                db.or_(
                    Tool.name.ilike(f"%{q}%"),
                    Tool.tagline.ilike(f"%{q}%"),
                    Tool.description.ilike(f"%{q}%"),
                    Tool.category_id == Category.id,
                    Category.name.ilike(f"%{q}%"),
                )
            )

        cat_slug = request.args.get("category", "")
        if cat_slug:
            cat = Category.query.filter_by(slug=cat_slug).first()
            if cat:
                query = query.filter_by(category_id=cat.id)

        pricing = request.args.get("pricing", "")
        if pricing:
            query = query.filter_by(pricing=pricing)

        sort = request.args.get("sort", "newest")
        if sort == "rating":
            query = query.order_by(Tool.rating.desc())
        elif sort == "name":
            query = query.order_by(Tool.name.asc())
        else:
            query = query.order_by(Tool.created_at.desc())

        page = request.args.get("page", 1, type=int)
        if page < 1:
            page = 1
        pagination = query.paginate(
            page=page, per_page=app.config["PER_PAGE"], error_out=False
        )

        active_category = (
            Category.query.filter_by(slug=cat_slug).first() if cat_slug else None
        )

        return render_template(
            "tools.html",
            tools=pagination.items,
            pagination=pagination,
            q=q,
            active_category=active_category,
            active_pricing=pricing,
            active_sort=sort,
        )

    @app.route("/tools/<slug>")
    def tool_detail(slug):
        tool = Tool.query.filter_by(slug=slug, is_approved=True).first_or_404()
        related = (
            Tool.query.filter(
                Tool.category_id == tool.category_id,
                Tool.id != tool.id,
                Tool.is_approved == True,
            )
            .order_by(Tool.rating.desc())
            .limit(4)
            .all()
        )

        is_favorited = is_tool_favorited(tool.id)

        return render_template(
            "tool_detail.html",
            tool=tool,
            related=related,
            is_favorited=is_favorited,
        )

    @app.route("/categories/<slug>")
    def category(slug):
        category = Category.query.filter_by(slug=slug).first_or_404()
        page = request.args.get("page", 1, type=int)
        if page < 1:
            page = 1
        pagination = (
            Tool.query.filter_by(category_id=category.id, is_approved=True)
            .order_by(Tool.rating.desc())
            .paginate(page=page, per_page=app.config["PER_PAGE"], error_out=False)
        )
        return render_template(
            "category.html",
            category=category,
            tools=pagination.items,
            pagination=pagination,
        )

    @app.route("/search")
    def search():
        q = request.args.get("q", "").strip()
        if not q:
            return redirect(url_for("tools"))
        return redirect(url_for("tools", q=q))

    @app.route("/submit", methods=["GET", "POST"])
    def submit():
        if request.method == "POST":
            check_csrf()
            name = request.form.get("name", "").strip()
            website = request.form.get("website_url", "").strip()
            category_id = request.form.get("category_id", type=int)
            tagline = request.form.get("tagline", "").strip()
            description = request.form.get("description", "").strip()
            pricing = request.form.get("pricing", "").strip()
            features_raw = request.form.get("features", "").strip()

            errors = []
            if not name or len(name) < 2:
                errors.append("Name is required (at least 2 characters).")
            if not website or not (
                website.startswith("http://") or website.startswith("https://")
            ):
                errors.append(
                    "A valid website URL is required (must start with http:// or https://)."
                )
            if not category_id:
                errors.append("Please select a category.")
            if not description or len(description) < 20:
                errors.append("Description is required (at least 20 characters).")
            if not pricing:
                errors.append("Please select a pricing model.")

            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("submit.html", form=request.form)

            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            existing = Tool.query.filter_by(slug=slug).first()
            if existing:
                slug = f"{slug}-{secrets.token_hex(4)}"

            features = json.dumps(
                [f.strip() for f in features_raw.split(",") if f.strip()]
            )

            tool = Tool(
                name=name,
                slug=slug,
                tagline=tagline,
                description=description,
                features=features,
                pricing=pricing,
                pricing_details=request.form.get("pricing_details", "").strip(),
                website_url=website,
                category_id=category_id,
                is_approved=False,
                rating=0.0,
                review_count=0,
            )
            db.session.add(tool)
            db.session.commit()

            flash(
                "Thank you! Your tool has been submitted for review. "
                "It will appear on the site once approved.",
                "success",
            )
            return redirect(url_for("submit"))

        return render_template("submit.html", form=None)

    @app.route("/favorites/<int:tool_id>", methods=["POST"])
    def toggle_favorite(tool_id):
        tool = Tool.query.get_or_404(tool_id)
        sid = get_session_id()

        existing = Favorite.query.filter_by(tool_id=tool_id, session_id=sid).first()

        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify({"action": "removed", "count": get_fav_count()})
        else:
            fav = Favorite(tool_id=tool_id, session_id=sid)
            db.session.add(fav)
            db.session.commit()
            return jsonify({"action": "added", "count": get_fav_count()})

    @app.route("/favorites")
    def favorites():
        get_session_id()
        sid = session["session_id"]

        favs = (
            Favorite.query.filter_by(session_id=sid)
            .order_by(Favorite.created_at.desc())
            .all()
        )

        tool_ids = [f.tool_id for f in favs]
        tools = (
            Tool.query.filter(Tool.id.in_(tool_ids), Tool.is_approved == True).all()
            if tool_ids
            else []
        )

        tool_map = {t.id: t for t in tools}
        ordered_tools = [tool_map[tid] for tid in tool_ids if tid in tool_map]

        return render_template("favorites.html", tools=ordered_tools)

    # ─── Admin Routes ─────────────────────────────────────────────
    @app.route("/admin")
    def admin():
        pending = (
            Tool.query.filter_by(is_approved=False)
            .order_by(Tool.created_at.desc())
            .all()
        )

        search_q = request.args.get("q", "").strip()
        all_tools_query = Tool.query
        if search_q:
            all_tools_query = all_tools_query.filter(
                db.or_(
                    Tool.name.ilike(f"%{search_q}%"),
                    Tool.tagline.ilike(f"%{search_q}%"),
                )
            )
        all_tools_query = all_tools_query.order_by(Tool.created_at.desc())
        page = request.args.get("page", 1, type=int)
        if page < 1:
            page = 1
        all_tools_pagination = all_tools_query.paginate(
            page=page, per_page=20, error_out=False
        )
        all_tools = all_tools_pagination.items

        stats = {
            "total": Tool.query.count(),
            "approved": Tool.query.filter_by(is_approved=True).count(),
            "pending": Tool.query.filter_by(is_approved=False).count(),
            "categories": Category.query.count(),
        }
        return render_template(
            "admin.html",
            pending=pending,
            stats=stats,
            all_tools=all_tools,
            all_tools_pagination=all_tools_pagination,
        )

    @app.route("/admin/approve/<int:tool_id>", methods=["POST"])
    def admin_approve(tool_id):
        check_csrf()
        tool = Tool.query.get_or_404(tool_id)
        tool.is_approved = True
        db.session.commit()
        flash(f'"{tool.name}" has been approved and is now live!', "success")
        return redirect(url_for("admin"))

    @app.route("/admin/delete/<int:tool_id>", methods=["POST"])
    def admin_delete(tool_id):
        check_csrf()
        tool = Tool.query.get_or_404(tool_id)
        name = tool.name
        db.session.delete(tool)
        db.session.commit()
        flash(f'"{name}" has been deleted.', "success")
        return redirect(url_for("admin"))

    # ─── API Routes ───────────────────────────────────────────────
    @app.route("/api/tools")
    def api_tools():
        query = Tool.query.filter_by(is_approved=True)

        limit = request.args.get("limit", 12, type=int)
        limit = min(limit, 50)
        sort = request.args.get("sort", "rating")
        cat = request.args.get("category", "")

        if cat:
            c = Category.query.filter_by(slug=cat).first()
            if c:
                query = query.filter_by(category_id=c.id)

        if sort == "rating":
            query = query.order_by(Tool.rating.desc())
        elif sort == "newest":
            query = query.order_by(Tool.created_at.desc())
        else:
            query = query.order_by(Tool.name.asc())

        tools = query.limit(limit).all()
        return jsonify(
            {
                "tools": [t.to_dict() for t in tools],
                "count": len(tools),
            }
        )

    @app.route("/api/categories")
    def api_categories():
        cats = Category.query.order_by(Category.name).all()
        return jsonify({"categories": [c.to_dict() for c in cats]})

    @app.route("/api/search")
    def api_search():
        q = request.args.get("q", "").strip()
        if not q or len(q) < 2:
            return jsonify({"results": []})

        results = (
            Tool.query.filter(
                Tool.is_approved == True,
                db.or_(
                    Tool.name.ilike(f"%{q}%"),
                    Tool.tagline.ilike(f"%{q}%"),
                ),
            )
            .limit(8)
            .all()
        )

        return jsonify(
            {
                "results": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "slug": t.slug,
                        "tagline": t.tagline,
                        "pricing": t.pricing,
                        "category": t.category.name,
                        "rating": t.rating,
                    }
                    for t in results
                ]
            }
        )

    # ─── Init DB ─────────────────────────────────────────────────
    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
