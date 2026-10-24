import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "studyhub.settings")
import django

django.setup()

from django.contrib.auth.models import User
from django.test import Client

c = Client()
c.force_login(User.objects.get(pk=25))
resp = c.get("/shared/")
html = resp.content.decode()

start = html.find('id="section-given"')
end = html.find("</section>", start)
section = html[start:end]
section = re.sub(r"\n\s*", "\n", section)
print(section[:11000])
