import logging
import secrets
from datetime import timedelta
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from social_django.models import UserSocialAuth
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.template.loader import render_to_string

log = logging.getLogger(__name__)

@receiver(post_save, sender=UserSocialAuth)
def send_welcome_email_on_social_auth(sender, instance, created, **kwargs):
    """
    Hook được gọi khi user liên kết tài khoản mạng xã hội (VD: Google).
    Chỉ áp dụng khi UserSocialAuth mới được tạo (created=True)
    và User cũng vừa mới được tạo (date_joined cách đây < 5 phút).
    """
    if not created:
        return

    user = instance.user
    
    # Kiểm tra xem user có phải mới tạo không
    if user.date_joined < timezone.now() - timedelta(minutes=5):
        # User đã tồn tại từ lâu, chỉ là mới link Google -> Bỏ qua không gửi mail và không đổi pass
        return

    # Sinh password ngẫu nhiên (12 ký tự)
    # Loại bỏ các ký tự dễ nhầm lẫn như I, l, O, 0
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%^&*"
    new_password = ''.join(secrets.choice(alphabet) for _ in range(12))
    
    # Ghi đè password và kích hoạt tài khoản
    user.set_password(new_password)
    user.is_active = True
    user.save(update_fields=['password', 'is_active'])
    
    log.info(f"[LANDA SSO] Generated new local password for Google SSO user: {user.email}")
    
    # Gửi email
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@landa.vn')
        context = {
            'name': getattr(user.profile, 'name', user.username) if hasattr(user, 'profile') else user.username,
            'username': user.username,
            'password': new_password,
            'lms_url': getattr(settings, 'LMS_ROOT_URL', 'http://local.openedx.io')
        }
        
        # HTML template
        html_content = render_to_string('landa_welcome_email.html', context)
        # Plain text fallback
        text_content = (
            f"Chào {context['name']},\n\n"
            f"Tài khoản E-learning của bạn đã được tạo thành công.\n"
            f"Tên đăng nhập: {context['username']}\n"
            f"Mật khẩu: {context['password']}\n\n"
            f"Bạn có thể đổi mật khẩu sau khi đăng nhập lần đầu.\n"
            f"Link đăng nhập: {context['lms_url']}"
        )
        
        msg = EmailMultiAlternatives(
            subject='[L&A E-learning] Thông tin đăng nhập tài khoản',
            body=text_content,
            from_email=from_email,
            to=[user.email],
        )
        msg.attach_alternative(html_content, 'text/html')
        msg.send(fail_silently=False)
        log.info(f"[LANDA SSO] Successfully sent welcome email to {user.email}")
    except Exception as e:
        log.error(f"[LANDA SSO] Failed to send welcome email to {user.email}: {str(e)}")
