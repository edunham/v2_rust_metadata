Rust Buildbot's Metadata Generation Tool
========================================

This is almost certainly not the script you are looking for. It's packaged as
a system utility solely because that makes it easier to install and invoke
The only place it's needed is on the `Rust`_ project's `buildmaster`_. 

A long time ago in a 2015 far, far away, the Rust infrastructure people
decided it should be easier to install a Rust toolchain capable of
cross-compiling for arbitrary targets. To cross compile for a given platform,
you need a ``rustc`` that was compiled for your **host** and a ``std`` that
was compiled for the **target**. The old metadata format only contained
filenames of tarballs, which don't carry enough information (especially
regarding versions and components) for a tool to piece together a
cross-compatible toolchain that actually works. 

So they sat in a room and argued for a few hours and came up with a new format
for Metadata V2. The new manifests are in ``.toml`` format, because that's
what Cargo uses and it supports comments. 

The old manifests worked by redirecting the stdout of ``ls`` into the desired
file, and this tool is meant to be invoked the same way to avoid adding
unnecessary complexity to Buildbot. 

.. _Rust: https://www.rust-lang.org/
.. _buildmaster: https://github.com/rust-lang/rust-buildbot
