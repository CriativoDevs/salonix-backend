from django.db import models


class PublicPage(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    ]

    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    content = models.TextField()
    image = models.ImageField(upload_to="cms/images/", blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    scheduled_publish_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Se definido, a pagina sera publicada automaticamente neste horario.",
    )
    published_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-published_at", "-created_at")
        indexes = [
            models.Index(fields=["slug"], name="cms_page_slug_idx"),
            models.Index(fields=["status"], name="cms_page_status_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.status})"

    def publish(self):
        from django.utils import timezone

        self.status = self.STATUS_PUBLISHED
        if not self.published_at:
            self.published_at = timezone.now()
        self.save(update_fields=["status", "published_at", "updated_at"])

    def unpublish(self):
        self.status = self.STATUS_DRAFT
        self.save(update_fields=["status", "updated_at"])


class PageSEO(models.Model):
    page = models.OneToOneField(
        PublicPage,
        on_delete=models.CASCADE,
        related_name="seo",
    )
    meta_title = models.CharField(max_length=70, blank=True)
    meta_description = models.CharField(max_length=160, blank=True)

    def __str__(self):
        return f"SEO: {self.page.title}"


class RoadmapItem(models.Model):
    STATUS_PLANNED = "planned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DELIVERED = "delivered"
    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planejado"),
        (STATUS_IN_PROGRESS, "Em andamento"),
        (STATUS_DELIVERED, "Entregue"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    order = models.PositiveIntegerField(default=0, help_text="Menor numero aparece primeiro.")
    is_visible = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "created_at")
        indexes = [
            models.Index(fields=["is_visible", "order"], name="cms_roadmap_visible_order_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
