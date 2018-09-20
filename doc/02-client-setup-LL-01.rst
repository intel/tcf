from source::

   $ git clone http://github.com/intel/tcf tcf.git
   $ pip2 install --user -r tcf.git/requirements.txt
   $ cd tcf.git
   $ python setup.py install --user
   $ cd zephyr
   $ python setup.py install --user

.. note:: depending on what you are trying to build, you might
          need to install :ref:`extra dependencies
          <install_support_pkgs>` that are not RPM packaged.
