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
    global listdir
   # Extract arguments from argv
    parser = argparse.ArgumentParser(description='Read inputs')
    parser.add_argument('-l','--listdir', 
                        help="examples: /home/build/master/artefacts/")
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
    if args['listdir']:
        listdir = args['listdir']
        if not listdir.endswith('/'):
            listdir += '/'
    else:
        listdir = '.'
    if  args['s3_addy'] and "dev-static-rust-lang-org" in args['s3_addy']:
        url_base = "https://dev-static.rust-lang.org"
    else:
        url_base = "https://static.rust-lang.org"


def print_preamble():
    # A manifest will always start with the version and date.
    print 'manifest_version = "2"' 
    print 'date = "%s"' % strftime("%Y-%m-%d")


def build_metadata():
    global all_metadata
    global all_triples
    all_triples = []
    files = [f for f in os.listdir(listdir) if os.path.isfile(listdir + f)]
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
            with open(listdir + a) as s:
                h = hashlib.sha256()
                h.update(s.read())
                shasum = h.hexdigest()
            (version, comp_list) = read_archive(listdir + a)
            all_triples += [triple]
            all_metadata[this_comp]['version'] = version
            all_metadata[this_comp]['components'] = comp_list
            # FIXME: Assumption that this script runs on same day as artifacts
            # are placed. Worst case, this could be a day EARLIER, since
            # script output gets uploaded along with other artifacts
            url = url_base + '/' + remote_dist_dir + '/' + strftime("%Y-%m-%d") + '/' + a
            all_metadata[this_comp]['triples'][triple] = {'url': url,'hash': shasum, 'filename': a}


def decompose_name(filename, channel):
    # ASSUMPTIONS: 
    #   * component names do not occur in triples
    #   * the filename ends with .tar.gz
    #   * Things are mostly hyphen-separated
    #   * We only want packages where the channel occurrs in the filename
 
    #   rust-docs   -   nightly   -   i686-apple-darwin    .tar.gz
    #    \    /            |              \    /              |
    #   component       channel           triple          extension
    valid_components = [
                        "cargo",
                        "rust",
                        "rust-docs",
                        "rust-mingw",
                        "rust-std",
                        "rustc",
                        ]
    debug("decomposing " + filename)
    # Strip extension. TODO: handle non-tgz
    if filename.endswith(".tar.gz"):
        filename = filename[:-7]
    if channel not in filename:
        return
    # still here? filename looks like rust-docs--i686-apple-darwin
    (component, triple) = [f.strip('-') for f in filename.split(channel)]
    if component not in valid_components:
        return
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
    print "[pkg.rust]"
    rust_version = c['version']
    if not isinstance(rust_version, basestring):
        e = "No rust-" + channel + "-*.tgz packages were found in " + listdir
        raise Exception(e)
    print '    version = "%s"' % rust_version
    if 'src' in c['triples']:
        print "    [pkg.%s.src]" % ('rust', src)
        print '        url = "%s"' % c['triples'][src]['url']
        print '        hash = "%s"' % c['triples'][src]['hash']
        c['triples'].remove('src')
    
    exts = []
    for t in sorted(c['triples']):
        # Each triple has url & hash, components each with pkg and target,
        # extensions each with pkg & target, and later installers each with
        # type, url, and hash. 
        print "    [pkg.%s.target.%s]" % ('rust', t)
        print '        url = "%s"' % c['triples'][t]['url']
        print '        hash = "%s"' % c['triples'][t]['hash']
        for comp in sorted(c['components']):
            if t in all_metadata[comp]['triples']:
                # we have the version of the component that matches the
                # triple. This handles the matching std as a component, as
                # well.
                print "        [[pkg.%s.target.%s.components]]" % (component, t)
                print '            pkg = "%s"' % comp
                print '            target = "%s"' % target
            elif comp == 'std':
                # this is a std for some other triple. It's an extension.
                exts.append('        [[pkg.%s.target.%s.extensions]]' % (component, t))
                exts.append('            pkg = "%s"' % comp)
                exts.append('            target = "%s"' % trip)
            elif len(all_metadata[comp]['triples']) > 0:
                # The package wants this component, it's not a std, and we
                # can't find a matching triple of the component anywhere.
                # If the component is available for any triples, give the
                # package one of them. 
                # FIXME this picks the alphabetically last available triple for the
                # component, because that'll grab x86_64-unknown-linux-gnu when it's
                # available and it's more repeatable and likely to be right
                # than picking at random
                target = sorted(all_metadata[comp]['triples'], reverse=True)[0]
                print "        [[pkg.%s.target.%s.components]]" % (component, t)
                print '            pkg = "%s"' % comp
                print '            target = "%s"' % target

    for e in exts:
            print e


def print_component_metadata(c):
    print "[pkg.%s]" % c
    comp_version = all_metadata[c]['version']
    if not isinstance(comp_version, basestring):
        comp_version = rust_version
    if len(comp_version) <= 3:
        comp_version = rust_version
    print '    version = "%s"' % comp_version
    trips = all_metadata[c]['triples']
    if 'src' in trips:
        print "    [pkg.%s.src]" % c
        print '        url = "%s"' % trips[src]['url']
        print '        hash = "%s"' % trips[src]['hash']
    for possibility in all_triples:
        print '    [pkg.%s.target.%s]' % (c, possibility)
        if possibility in trips:
            print '        available = true'
            print '        url = "%s"' % trips[possibility]['url']
            print '        hash = "%s"' % trips[possibility]['hash']
        else:
            print '        available = false'
         
def main():
    # Not every component (docs, etc.) carries around the rust version string.
    # This global holds the version string for rust proper so it can be filled in
    # on those all_metadata which are missing it.
    global rust_version
    global all_triples
    get_arguments()
    print_preamble()
    build_metadata()
    all_triples = sorted(list(set(all_triples)))
    all_triples.remove("src") # src is special
    debug(all_metadata)
    # FIXME: Maybe don't assume we always have Rust? But we probably always
    # have Rust, and its metadata is quite different from components.
    print_rust_metadata()
    for c in sorted(all_metadata):
        if c != 'rust':
            print_component_metadata(c)


if __name__ == "__main__":
    main()
