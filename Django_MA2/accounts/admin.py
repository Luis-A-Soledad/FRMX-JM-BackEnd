from django.contrib import admin

from .models import Role, UserProfile


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at")
    search_fields = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "created_at")
    search_fields = ("user__username", "role__name")
    list_filter = ("role",)
