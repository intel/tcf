::

  # echo insecure > ~/.curlrc       # Don't mind the SSL certificate for RPM
  # rpm -i https://RPMREPOHOST/repo/tcf-repo-v0-1-1.noarch.rpm
  # dnf install -y --best --allowerasing ttbd-zephyr tcf-zephyr
  # systemctl enable ttbd@production
  # systemctl start ttbd@production

Note:

- *insecure* tells the ``rpm -i`` command to bypass the HTTPS
  certificate check, as we might not have it yet in our certificate
  database.
