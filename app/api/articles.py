"""
学习文章管理 API
对应 DESIGN-ARTICLES.md 4.1 文章管理

所有端点受 AuthMiddleware 保护（全局配置）。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Article
from app.services.code_ref_parser import CodeRefParser
from app.services.local_code_sync import LocalCodeSyncService
from app.services.article_renderer import ArticleRenderer
from app.services.article_validator import ArticleValidator

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== Pydantic 请求/响应模型 =====

class ArticleCreate(BaseModel):
    title: str
    content: str
    area: Optional[str] = ""
    tags: Optional[list] = []
    status: Optional[str] = "draft"


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    area: Optional[str] = None
    tags: Optional[list] = None
    status: Optional[str] = None


class PreviewRequest(BaseModel):
    content: str


class ValidateRequest(BaseModel):
    deep_check: bool = False


# ===== 助手函数 =====

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _article_to_response(a: Article) -> dict:
    """Article ORM → JSON dict"""
    d = a.to_dict()
    return d


# ===== 文章 CRUD =====

@router.get("/")
async def list_articles(
    area: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(all|draft|published|archived)?$"),
    tag: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("updated", pattern="^(created|updated|title)$"),
    sort_order: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    """获取文章列表"""
    query = db.query(Article)

    if area:
        query = query.filter(Article.area == area)
    if status and status != "all":
        query = query.filter(Article.status == status)
    if tag:
        query = query.filter(Article.tags.contains(tag))

    # 排序
    sort_col = {
        "created": Article.created_at,
        "updated": Article.updated_at,
        "title": Article.title,
    }.get(sort_by, Article.updated_at)

    if sort_order == "desc":
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())

    articles = query.all()
    return {
        "articles": [_article_to_response(a) for a in articles],
        "total": len(articles),
    }


@router.post("/")
async def create_article(req: ArticleCreate, db: Session = Depends(get_db)):
    """创建新文章"""
    now = _utcnow()
    article = Article(
        title=req.title,
        content=req.content,
        area=req.area or None,
        tags=json.dumps(req.tags, ensure_ascii=False) if req.tags else None,
        status=req.status or "draft",
        created_at=now,
        updated_at=now,
    )
    db.add(article)
    db.commit()
    db.refresh(article)

    # 解析代码引用
    parser = CodeRefParser()
    refs_result = parser.save_article_refs(article.id, article.content, db)

    return {
        "id": article.id,
        "title": article.title,
        "status": article.status,
        "created_at": article.created_at.isoformat(),
        "refs_count": refs_result["total_refs"],
    }


@router.put("/{article_id}")
async def update_article(article_id: int, req: ArticleUpdate, db: Session = Depends(get_db)):
    """更新文章"""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    if req.title is not None:
        article.title = req.title
    if req.content is not None:
        article.content = req.content
    if req.area is not None:
        article.area = req.area or None
    if req.tags is not None:
        article.tags = json.dumps(req.tags, ensure_ascii=False)
    if req.status is not None:
        article.status = req.status

    article.updated_at = _utcnow()

    # 重新解析代码引用
    parser = CodeRefParser()
    refs_result = parser.save_article_refs(article.id, article.content, db)

    # 清除渲染缓存
    article.rendered_html = None

    db.commit()

    return {
        "id": article.id,
        "title": article.title,
        "updated_at": article.updated_at.isoformat(),
        "refs_count": refs_result["total_refs"],
    }


@router.delete("/{article_id}")
async def delete_article(article_id: int, db: Session = Depends(get_db)):
    """删除文章（级联删除 CodeReference）"""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    db.delete(article)
    db.commit()
    return {"deleted": True, "id": article_id}


@router.get("/{article_id}")
async def get_article(article_id: int, db: Session = Depends(get_db)):
    """获取单篇文章详情"""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return _article_to_response(article)


# ===== 渲染 =====

@router.get("/{article_id}/rendered")
async def render_article(article_id: int, sync_code: bool = Query(False), db: Session = Depends(get_db)):
    """获取渲染后的文章 HTML，代码引用被替换为实际代码片段"""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    cache_service = LocalCodeSyncService(db)
    renderer = ArticleRenderer(cache_service, db)
    result = renderer.render_article(article_id, sync_code=sync_code)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return {
        "id": article.id,
        "title": article.title,
        "html": result["html"],
        "embedded_codes": result["embedded_codes"],
    }


@router.post("/{article_id}/preview")
async def preview_article(article_id: int, req: PreviewRequest, db: Session = Depends(get_db)):
    """预览文章渲染结果（不保存到数据库）"""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    cache_service = LocalCodeSyncService(db)
    renderer = ArticleRenderer(cache_service, db)
    result = renderer.render_preview(req.content)

    return {
        "html": result["html"],
        "refs": result["refs"],
    }


# ===== 验证 =====

@router.post("/{article_id}/validate")
async def validate_article(article_id: int, req: ValidateRequest, db: Session = Depends(get_db)):
    """验证单篇文章中的所有代码引用"""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    cache_service = LocalCodeSyncService(db)
    validator = ArticleValidator(cache_service, db)
    result = validator.validate_article(article_id, deep_check=req.deep_check)

    return result


@router.post("/batch-validate")
async def batch_validate_articles(req: ValidateRequest, db: Session = Depends(get_db)):
    """批量验证所有文章中的代码引用"""
    cache_service = LocalCodeSyncService(db)
    validator = ArticleValidator(cache_service, db)
    result = validator.batch_validate(deep_check=req.deep_check)
    return result