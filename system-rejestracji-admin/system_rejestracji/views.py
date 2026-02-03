from schedule.views import CalendarView
from .models import Wizyta

class UserCalendarView(CalendarView):
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_superuser:
            return qs
        return qs.filter(user=self.request.user)

