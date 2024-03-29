Contributing
============

Checkout your code in (eg) `~/tcf.git`

.. include:: 02-guide-contributing-LL-clone.rst

.. note:: we are on the v0.11 stabilization branch (otherwise, you'd
          clone *master*).

.. _support_and_reporting_issues:

Support & reporting issues
--------------------------

.. include:: 02-guide-contributing-LL-issues.rst

.. _tcf_run_from_source_tree:

Running the TCF client from the source tree
-------------------------------------------

If you are developing TCF client code, it is helpful to be able to run
the local, checked out copy of the code rather than having to install
system wide.

For that, you can set the configuration::

  $ mkdir ~/.tcf
  $ cd ~/.tcf
  $ ln -s ~/tcf.git/conf_*.py .

If you have installed TCF systemwide, you might have to remove
`/etc/tcf/conf_zephyr.py` or alternatively, pass ``--config-path
:~/tcf.git/zephyr``, but it can be repetitive (the initial `:` removes
the predefined path `/etc/tcf`).

And now you can run::

  $ cd anywhere
  $ ~/tcf.git/tcf command...

Add servers as needed in your toplevel `~/.tcf` or `/etc/tcf/`::

     $ echo "tcfl.config.url_add('https://SERVER:5000', ssl_ignore = True)" >> conf_servers.py

A useful trick to be able to quickly switch servers (when only
wanting to work on a set of servers S1 versus a set of servers
S2):

- Create directory `~/s/S1`, add a conf_server.py there pointing to
  the servers in said set; when running tcf, use::

     $ ~/tcf.git/tcf --config-path ~/s/S1 COMMAND

- Maybe easier, is to call the directory `~/s/S1/.tcf`, cd into
  `~/s/S1` and run tcf from there::

    $ cd ~/s/S1
    $ ~/tcf.git/tcf command...

  I have different directories, one call `production/.tcf` with all the
  production servers, another `staging/.tcf`, with all the test servers,
  `local/.tcf`, for my local server, etc...

  
.. _running_server_source:
  
Running the TCF server (ttbd) from the source tree
--------------------------------------------------

If you are developing TCF server code, running said code without
installing system wide (and potentially conflicting versions),
requires some setup. This is usually called the *staging* server,
running locally on your machine:

0. Install dependencies:

   - Fedora / RHEL / CentOS, client::
     
       # dnf install -y \
         android-tools \
         gvnc-tools \
         make \
         python3-ply \
         python3-pykwalify \
         python3-requests \
         python3-Levenshtein \
         python3-jinja2 \
         python3-junit_xml \
         python3-keyring \
         python3-numpy \
         python3-opencv \
         python3-pyyaml

     server::

       # dnf install -y \
         alsa-utils \
         android-tools \
         dfu-util \
         dosfstools \
         gcc \
         git \
         httpd \
         ipmitool \
         libcap-devel \
         livecd-tools \
         make \
         openocd \
         openssh-clients \
         parted \
         python3-pexpect \
         python3-pyOpenSSL \
         python3-pyserial \
         python3-flask \
         python3-flask-login \
         python3-flask-principal \
         python3-ldap \
         python3-ply \
         python3-requests \
         python3-systemd \
         python3-tornado \
         python3-werkzeug \
         python3-devel \
         python3-keyring \
         python3-pysnmp \
         python3-pyusb \
         qemu \
         socat \
         sshpass \
         tftp-server \
         v4l-utils
       $ pip3 install --user sdnotify python-prctl

     If you will be isntrumenting targets with video capture, you
     might need *ffmpeg* installed on your servers (see
     https://rpmfusion.org/Configuration) and then::

       # dnf install -y ffmpeg

     or::

       # yum install -y ffmpeg
     
   - pure PIP3 dependencies::

         $ pip3 install --user \
            Flask              \
            Flask-Login        \
            Flask-Principal    \
            Jinja2             \
            Werkzeug           \
            keyring            \ 
            ply                \
            python-prctl       \
            pykwalify          \
            pyserial           \
            python-Levenshtein \
            pyusb              \
            setuptools         \
            tornado
       
1. Disable SELinux (to be able to run from your home directory)::

   # setenforce 0

2. there is no step two anymore

3. Ensure your home directory and such are readable by users members
   of your group::

     $ chmod g+rX ~
     $ chmod -R g+rX ~/tcf.git

4. Create a user and group *ttbd*::

     # useradd -U ttbd
     
4. Create a staging configuration directory `/etc/ttbd-staging`, make it
   owned by your user, so you don’t have to work as root::

     $ sudo install -d -o $LOGNAME -g $LOGNAME /etc/ttbd-staging

   (note you can also create a config file ``conf_NAME.py`` anywhere
   and invoke later with ``--config-file conf_NAME.py``.
     
5. link the following config files from your source tree::

     $ ln -s ~/tcf.git/ttbd/conf_0*.py /etc/ttbd-staging

6. Create a local configuration, so you can login without a password
   from the local machine to port 5001 (port 5000 we leave it for
   production instances)::

     $ cat > /etc/ttbd-staging/conf_local.py <<EOF
     local_auth.append(“127.0.0.1”)
     host = “0.0.0.0”
     port = 5001
     EOF

   To have TCF use this daemon, add a configuration line::

     tcfl.config.url_add('https://SERVER:5001', ssl_ignore = True)

   to any TCF config file which your client will read.

7. Create a local configuration file `conf_10_local.py` with local
   configuration statements to enable hardware as needed. The default
   configuration has only virtual machines.

8. To start manually, running on the console::

     $ ttbd --config-path :/etc/ttbd-staging -vvvv

   Depending on your user's permissions and privleges, you might not
   be able to access certain system features or hardware devices. Or
   if there is a config file that you want used anywhere else::

     $ ttbd --config-file conf_NAME.py -vvvv

   which can be combined also with ``--config-path`` to load both.
   
9. (optionally) To start using *systemd* create a configuration for
   systemd to start the daemon::

     # cp ~/tcf.git/ttbd/ttbd@.service /etc/systemd/system/ttbd@staging.service

   Edit said file and:

   - In *Supplementary groups*, append your login name, so the process
     can access your home directory

   - In *ExecStart*, replace `/usr/bin/ttbd` with
     `/home/USERNAME/tcf.git/ttbd/ttbd` so it starts the copy of the
     daemon you are working on

     (note if you ever need to run *strace* on the daemon, you can
     prefix `/usr/bin/strace -f -o /tmp/ttbd.strace.log` to record
     every single system call...for those hard debug cases :)

   - Reload the systemd configuration::

       # systemctl daemon-reload

Start the daemon with::

  # systemctl restart ttbd@staging

Make it always start automatically with::

  # systemctl enable ttbd@staging


Manual installation of rsync server for Provisioning OS
-------------------------------------------------------

To setup a system wide rsync server, along other services, instead of
relying on ttbd starting a specific instance for each network, follow
these instructions:

a. Install rsync

b. configure rsync to export */home/ttbd/images* as read only,
   appending to */etc/rsyncd.conf*::

     # TCF provisioning
     # We run the daemon as root and need to run as root so we can access
     # folders that have root-only weird permissions
     [images]
     path = /home/ttbd/images
     read only = True
     timeout = 300
     # need root perms in this images so we can read all files and transfer
     # them properly, even those that seem closed; that's how the oS images
     # are
     uid = root
     gid = root

   Ensure daemon is listening on the interfaces where the targets
   will call from, like for example:

     address = 0.0.0.0

   Ensure port 873 (rsync) is open on the firewall::

    # firewall-cmd --zone=public --add-port=873/tcp --permanent
    # firewall-cmd --zone=public --add-service=rsyncd --permanent

c. Enable and start the rsync service::

     # systemctl enable rsyncd
     # systemctl start rsyncd

d. test::

     $ rsync localhost::images/
     $ rsync localhost::images/tcf-live/x86_64/

   now lists what is in /home/ttbd/images and allows copying it



Workflow for contributions
--------------------------

Adapted from http://docs.zephyrproject.org/contribute/contribute_guidelines.html#contribution-workflow

Make small, logically self-contained, controlled changes to simplify
review.  Makes merging and rebasing easier, and keep the change
history clear and clean.

  .. admonition:: example

     cleaning up code would be a set of commits:

     - only whitespace changes to adapt to convention
     - fix one type of warnings
     - fix one type of errors
     - etc...

Provide as much information as you can about your change, update
appropriate documentation, and testing changes thoroughly before
submitting.

We accept contributions as GitHub pull requests, to save everyone's
time and provide a consistent review platform for all.

A github-based workflow can be:

1. Create a fork to your personal account on GitHub (click on the
   *fork* button in the top right corner of the project repo page in
   GitHub)

2. On your development computer, clone the fork you just made::

     $ git clone https://github.com/<your github id>/tcf.git

   Configure *git* to know about the upstream repo::

     $ git remote add upstream https://github.com/intel/tcf
     $ git remote -v

3. Create a topic branch (off of master or anyother branch) for your
   work (if you’re addressing an issue, we suggest including the issue
   number in the branch name)::

     $ git checkout master
     $ git checkout -b fix_comment_typo

   Make changes, test locally, change, test, test again; some base
   testcases we will run are at least::

     $ cd ~/tcf.git
     $ ./lint-all.py
     $ ./tcf run ~/tcf.git/tests

4. Start the pull request process by adding your changed files::

     $ git add [file(s) that changed, add -p if you want to be more specific]

   You can see files that are not yet staged using::

     $ git status

   Verify changes to be committed look as you expected::

     $ git diff --cached

5. Commit your changes to your local repo::

     $ git commit -vs

   ``-s`` option automatically adds your `Signed-off-by:` to your
   commit message. Your commit will be rejected without this line that
   indicates your agreement with the DCO (Developer Certificate of
   Origin).

   Commits messages shall be explanatory and concise, properly spelled
   and in the form::

     AREA: SHORT SUMMARY

     Longer description that can be obviated if the commit is quite
     obvious and/or the summary already says it all. Note
     implementation details shall be detailed in the code, it is ok
     for the commit message to point to those, as we don't want
     information duplicated innecesarily.

     Signed-off-by: Random Developer <random.developer@somewhere.org>

6. Push your topic branch with your changes to your fork in your
   personal GitHub account::

     $ git push origin fix_comment_typo

   a. In your web browser, go to your forked repo and click on the
      *Compare & pull request* button for the branch you just worked on
      and you want to open a pull request with.

   b. Review the pull request changes, and verify that you are opening a
      pull request for the appropriate branch. The title and message from
      your commit message should appear as well.

      GitHub will assign one or more suggested reviewers (based on the
      `CODEOWNERS` file in the repo). If you are a project member, you can
      select additional reviewers now too.

   c. Click on the *submit* button and your pull request is sent and
      awaits review. Email will be sent as review comments are made, or
      you can check on your pull request at
      https://github.com/intel/tcf/pulls.

   While you’re waiting for your pull request to be accepted and
   merged, you can create another branch to work on another issue (be
   sure to make your new branch off of master and not the previous
   branch)::

     $ git checkout master
     $ git checkout -b fix_another_issue

   and use the same process described above to work on this new topic
   branch.
