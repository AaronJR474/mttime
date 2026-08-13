.. _getting_started:

===============
Getting started
===============

Supported installation model
----------------------------

This fork is intended to be directly installable from Git. The upstream MTtime
core remains in ``mttime.core`` and the additive orchestration lives in
``mttime.workflows``.

The fork currently declares Python 3.8--3.12 support. The supported PyFK
workflow is Linux/WSL, while Syngine does not require PyFK.

Default Linux/WSL installation
------------------------------

.. code-block:: bash

   python -m pip install --upgrade pip
   python -m pip install "git+https://github.com/AaronJR474/mttime.git"

On Python 3.10--3.12 the installation pins the modernized PyFK PR #20 commit
recorded in ``setup.py`` because the currently published PyFK metadata remains
restricted to Python <3.10. Once upstream PyFK publishes a compatible release,
the direct VCS pin should be removed in favour of that release.

Installation without PyFK
--------------------------

On Linux/WSL, use the fork-specific build switch when only Syngine or externally
prepared Green's functions are needed:

.. code-block:: bash

   MTTIME_NO_PYFK=1 python -m pip install "git+https://github.com/AaronJR474/mttime.git"

Native Windows and macOS installations skip the automatic PyFK dependency in the
package metadata. This restriction is deliberate for this fork's supported/tested
PyFK route; it does not imply that every upstream PyFK configuration on every
other Unix-like platform is impossible.

Optional map plotting
---------------------

.. code-block:: bash

   python -m pip install "mttime[maps] @ git+https://github.com/AaronJR474/mttime.git"

Core MTtime usage
-----------------

.. code-block:: python

   import mttime

   config = mttime.Configure(path_to_file="mtinv.in")
   mt = mttime.Inversion(config=config)
   mt.invert()
   mt.write()

Workflow usage
--------------

.. code-block:: python

   from mttime.workflows import gf_helpers, mttime_helpers

The helpers are packaged with MTtime itself; copying ``workflows`` into a working
directory or editing ``PYTHONPATH`` is not required. Continue with
:ref:`workflows` for the end-to-end workflow and Green's-function choices.
