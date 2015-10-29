#! /usr/bin/env python
from time import strftime
import argparse
import sys
import tarfile
import hashlib
import os
from collections import defaultdict

# This tool builds Rust package manifests in the v2 (.toml) format. Manifests
# are for tools to use when finding and installing Rust and its various
# optional all_metadata, such as cross-compile-compatible variants of the
# standard library. 

# Takes s3_addy, remote_dist_dir, component, channel.
# Emits a full v2 manifest to stdout.

# m     component
# n     channel
# r     remote_dist_dir
# s     s3_addy

def autoviv():
    # thanks https://en.wikipedia.org/wiki/Autovivification
    return defaultdict(autoviv)

def debug(words):
    # print words
    pass


def get_arguments():
    global component
    global channel
    global url_base
    global remote_dist_dir
   # Extract arguments from argv
    parser = argparse.ArgumentParser(description='Read inputs')
    parser.add_argument('-m','--component', 
                        help="examples: rust-docs, rustc, cargo")
    parser.add_argument('-n','--channel', 
                        help="examples: beta, stable, nightly")
    parser.add_argument('-r','--remote_dist_dir', 
                        help="example: dist")
    parser.add_argument('-s','--s3_addy',
                        help="example: s3://static-rust-lang-org")
    args = vars(parser.parse_args())
    component = args['component']
    channel = args['channel']
    remote_dist_dir = args['remote_dist_dir']
    if "dev-static-rust-lang-org" in args['s3_addy']:
        url_base = "https://dev-static.rust-lang.org"
    else:
        url_base = "https://static.rust-lang.org"


def print_preamble():
    # A manifest will always start with the version and date.
    print 'manifest_version = "2"' 
    print 'date = "%s"' % strftime("%Y-%m-%d")


def build_metadata(path = os.getcwd()):
    global all_metadata
    files = [f for f in os.listdir(path) if os.path.isfile(f)]
    archives = [f for f in files if f.endswith('.tar.gz')]
    all_metadata = autoviv()
    for a in archives:
        d = decompose_name(a, channel)
        # d will return None if the archive is not in the channel we want
        if d:
            # d contains (triple, component)
            this_comp = d[1]
            triple = d[0]
            shasum = ''
            with open(a) as s:
                h = hashlib.sha256()
                h.update(s.read())
                shasum = h.hexdigest()
            (version, comp_list) = read_archive(a)
            all_metadata[this_comp]['version'] = version
            all_metadata[this_comp]['components'] = comp_list
            # FIXME: Assumption that this script runs on same day as artifacts
            # are placed. Worst case, this could be a day EARLIER, since
            # script output gets uploaded along with other artifacts
            url = url_base + '/' + remote_dist_dir + '/' + strftime("%Y-%m-%d") + '/' + a
            all_metadata[this_comp]['triples'][triple] = {'url': url,'hash': shasum, 'filename': a}


def decompose_name(filename, channel):
    # TODO: There must be a better way! Introspecting tarball names to make
    # reasonable judgements about component vs triple is currently a
    # nightmare.

    # ASSUMPTIONS: 
    #   * component names do not occur in triples
    #   * the filename ends with .tar.gz
    #   * Things are mostly hyphen-separated
    #   * We only want packages where the channel occurrs in the filename
 
    #   rust-docs   -   nightly   -   i686-apple-darwin    .tar.gz
    #    \    /            |              \    /              |
    #   component       channel           triple          extension

    debug("decomposing " + filename)
    # Strip extension. TODO: handle non-tgz
    if filename.endswith(".tar.gz"):
        filename = filename[:-7]
    pieces = filename.split('-')
    if not channel in pieces:
        return
    pieces.remove(channel)
    filename = '-'.join(pieces)
    # We don't know where the component ends and the triple starts yet. It's
    # easiest to find the triple by stripping all the words which only occur
    # in component names.
    comp_names = ['mingw', 'std', 'rust', 'docs', 'cargo', 'rustc' ]
    for p in comp_names:
        if p in pieces:
            pieces.remove(p)
    # Component, channel, and extension are gone now. Triple is left.
    triple = '-'.join(pieces)
    # Figure out what we stripped when removing strings that looked like
    # component names
    component = filename[:-(len(triple) + 1)]
    return (triple, component)


def read_archive(a):
    version = ''
    comp_list = [] 
    ar = tarfile.open(a, "r:gz")
    listing = ar.getmembers()
    for l in listing:
        path = l.name.split('/')
        if len(path) >= 2:
            if path[1] == 'version':
                f = ar.extractfile(l)
                version = f.read().strip()
                #debug("version: " + str(version))
            if path[1] == 'components':
                f = ar.extractfile(l)
                comp_list = f.read().split()
                #debug("all_metadata: " + str(all_metadata))
    ar.close()
    return (version, comp_list)


def print_rust_metadata():
    global rust_version
    c = all_metadata['rust']
    print "[rust]"
    rust_version = c['version']
    print '    version = "%s"' % rust_version
    for t in sorted(c['triples']):
        exts = []
        # Each triple has url & hash, components each with pkg and target,
        # extensions each with pkg & target, and later installers each with
        # type, url, and hash. 
        print "    [%s.%s]" % ('rust', t)
        print '        url = "%s"' % c['triples'][t]['url']
        print '        hash = "%s"' % c['triples'][t]['hash']
        for comp in sorted(c['components']):
            # Only include alternative triples in extensions if it's a std or
            # docs package, which we know by string compares on the name :(
            include_exts = 'std' in comp or 'docs' in comp
            target_missing = False
            # comp is like 'rustc', 'rust-docs', 'cargo'
            # component came in on command line
            print "        [[%s.%s.components]]" % (component, t)
            print '            pkg = "%s"' % comp
            # TODO: Handle divergent target triples. Metadata about what the
            # packaging script wants these to be isn't currently handed along
            # from that stage.
            if t in all_metadata[comp]['triples']:
                target = t
            elif len(all_metadata[comp]['triples']) > 0:
                # FIXME this picks the alphabetically last available triple for the
                # component, because that'll grab x86_64-unknown-linux-gnu when it's
                # available and I assume that's usually correct
                target = sorted(all_metadata[comp]['triples'], reverse=True)[0]
            else:
                target_missing = True
                target = t
            print '            target = "%s"' % target
            if include_exts and not target_missing:
                for trip in sorted(all_metadata[comp]['triples']):
                    # if trip == target, we have already printed it under
                    # 'components', so it's not an extension
                    if trip != target:
                        exts.append('        [[%s.%s.extensions]]' % (component, t))
                        exts.append('            pkg = "%s"' % comp)
                        exts.append('            target = "%s"' % trip)
        for e in exts:
            print e


def print_component_metadata(c):
    print "[%s]" % c
    comp_version = all_metadata[c]['version']
    if len(comp_version) <= 1:
        # Got something bogus like an empty dict or string. Fail over
        # to using the version of rust
        comp_version = rust_version
    print '    version = "%s"' % comp_version
    trips = all_metadata[c]['triples']
    for t in trips:
        print '    [%s.%s]' % (c, t)
        print '        url = "%s"' % trips[t]['url']
        print '        hash = "%s"' % trips[t]['hash']
         
         
def main():
    # Not every component (docs, etc.) carries around the rust version string.
    # This global holds the version string for rust proper so it can be filled in
    # on those all_metadata which are missing it.
    global rust_version
    get_arguments()
    print_preamble()
    build_metadata()
    debug(all_metadata)
    # FIXME: Maybe don't assume we always have Rust? But we probably always
    # have Rust, and its metadata is quite different from components.
    print_rust_metadata()
    for c in sorted(all_metadata):
        if c != 'rust':
            print_component_metadata(c)


if __name__ == "__main__":
    main()
