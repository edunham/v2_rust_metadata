#! /usr/bin/env python
from time import strftime
from datetime import date, timedelta
import argparse
import sys
import tarfile
import hashlib
import os
import urllib2
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

target_list = [ 
    "aarch64-unknown-linux-gnu",
    "arm-linux-androideabi",
    "arm-unknown-linux-gnueabif",
    "arm-unknown-linux-gnueabihf",
    "i686-apple-darwin",
    "i686-pc-windows-gnu",
    "i686-pc-windows-msvc",
    "i686-unknown-linux-gnu",
    "mips-unknown-linux",
    "mipsel-unknown-linux",
    "x86_64-apple-darwin",
    "x86_64-pc-windows-gnu",
    "x86_64-pc-windows-msvc",
    "x86_64-unknown-linux-gnu",
    "x86_64-unknown-linux-musl",
]

valid_components = [
                    "cargo",
                    "rust",
                    "rust-docs",
                    "rust-mingw",
                    "rust-std",
                    "rustc",
                    ]
valid_components.sort(key=len)

installer_exts = [
                 ".tar.gz",
                 ".msi",
                 ".exe",
                 ".pkg",
                 ]

class Meta:
    def __init__(self):
        self.component = None
        self.channel = None
        self.url_base = None
        self.remote_dist_dir = None
        self.directory_to_list = None
        self.pkgs = {}
        self.version = ""

    def add_pkg(self, pkg_name, url = None, version = None):
        try:
            # If it hasn't been added yet, this will KeyError
            if not self.pkgs[pkg_name]['version'] and version:
                self.pkgs[pkg_name]['version'] = version
        except KeyError:
            # TODO make a url if one wasn't provided 
            if pkg_name not in valid_components:
                return
            self.pkgs[pkg_name] = {}
            d = {}
            for t in target_list:
                d[t] = {}
            if version:
                self.pkgs[pkg_name]['version'] = version
            self.pkgs[pkg_name]['url'] = url
            self.pkgs[pkg_name]['src'] = {} 
            self.pkgs[pkg_name]['target'] = d

    def add_triple(self, pkg_name, triple, url, shasum, filename, comp_list = None):
        try:
            if triple == 'src':
                self.pkgs[pkg_name]['src'][triple] = {'url': url,'hash': shasum, 'filename': filename}
            self.pkgs[pkg_name]['target'][triple] = {'url': url,'hash': shasum, 'filename': filename}
            if comp_list:
                self.pkgs[pkg_name]['target'][triple]['components'] = comp_list
        except KeyError:
            e = "Tried to add triple " + triple + " to nonexistant package " + pkg_name
            raise Exception(e) 

    def get_cargo(self):
        self.add_pkg('cargo')
        # Cargo is built daily and dumped into baseurl/cargo-dist/
        response = urllib2.urlopen(self.url_base + "/cargo-dist/cargo-build-date.txt")
        cargo_date = response.read().split()[0]
        #try: # TODO read the toml manifest if it's there
        #    cargo_toml = urllib2.urlopen(self.url_base + "/cargo-dist/" + cargo_date + "/channel-")
        for t in target_list:
            try:
                filename = "cargo-" + self.channel + "-" + t + ".tar.gz"
                url = self.url_base + "/cargo-dist/" + cargo_date + "/" + filename
                shasum = urllib2.urlopen(url + ".sha256").read().split()[0]
                self.add_triple('cargo', t, url, shasum, filename)
            except:
                pass # No cargo for this date and triple

    def print_metadata(self):
        self.print_preamble() 
        if self.component != "cargo": 
            self.print_rust_metadata()
        for c in sorted(self.pkgs):
            if c != 'rust':
                self.print_pkg_metadata(c)
   
    def print_preamble(self):
        # A manifest will always start with the version and date.
        print 'manifest_version = "2"' 
        print 'date = "%s"' % strftime("%Y-%m-%d")

    def print_src_info(self, c):
        try:
            url = self.pkgs[c]['src']['url'] 
            shasum = self.pkgs[c]['src']['hash'] 
            print "    [pkg.%s.src]" % c
            print '        url = "%s"' % url
            print '        hash = "%s"' % shasum
        except KeyError:
            pass

    def print_target_info(self, c, t):
        print '    [pkg.%s.target.%s]' % (c, t)
        try:
            url = self.pkgs[c]['target'][t]['url']                
            sha = self.pkgs[c]['target'][t]['hash']                
            print '        available = true'
            print '        url = "%s"' % url
            print '        hash = "%s"' % sha
            return True
        except KeyError:
            print '        available = false'
            return False

    def print_pkg_metadata(self, c):
        print "[pkg.%s]" % c
        try:
            pkg_version = self.pkgs[c]['version']
            if not isinstance(pkg_version, basestring) or len(pkg_version) <= 3:
                pkg_version = self.pkgs['rust']['version']
        except KeyError:
            pkg_version = self.pkgs['rust']['version']
        print '    version = "%s"' % pkg_version
        self.print_src_info(c)
        for t in sorted(target_list):
            self.print_target_info(c, t)

    def print_rust_metadata(self):
        c = 'rust'
        print "[pkg.rust]"
        rust_version = self.pkgs['rust']['version']
        if not isinstance(rust_version, basestring):
            e = "No rust-" + self.channel + "-*.tgz packages were found in " + self.directory_to_list
            raise Exception(e)
        print '    version = "%s"' % rust_version
        self.print_src_info(c) 
        exts = []
        for t in sorted(target_list):
            target = t
            if self.print_target_info(c, t): # T/F = whether it's available
                for comp in sorted(self.pkgs['rust']['target'][target]['components']):
                    if comp not in valid_components:
                       try:
                            (target, comp) = decompose_name(comp, '-')
                       except: 
                            e = "components list asked for " + comp + ", wat?"
                            raise Exception(e) 
                    # the comp_list is from components file in the rust tarball
                    # A *component* has the same target as its parent.
                    # An *extension* has a differing target from its parent.
                    # "extensions are rust-std or rust-docs that aren't in the
                    # rust tarball's component list"
                    listed = False
                    try:
                        self.pkgs[comp]['target'][target]['url'] # Test availability
                        print "        [[pkg.%s.target.%s.components]]" % (c, t)
                        print '            pkg = "%s"' % comp
                        print '            target = "%s"' % target
                        listed = True
                    except KeyError:
                        # We do not have that component
                        pass
                    if not listed and ('std' in comp or 'docs' in comp):
                        # this is a std for some other triple. It's an extension.
                        exts.append('        [[pkg.%s.target.%s.extensions]]' % (c, t))
                        exts.append('            pkg = "%s"' % comp)
                        exts.append('            target = "%s"' % t)
                        listed = True
                    elif not listed and 'cargo' not in comp and 'docs' not in comp:
                        e = "Component " + comp + ' - ' + self.channel + ' - ' + t + " needed but not found"
                        # raise Exception(e)
                        pass
                for e in exts:
                    print e


def debug(words):
    # print words
    pass


def get_arguments(meta_obj):
   # Extract arguments from argv
    parser = argparse.ArgumentParser(description='Read inputs')
    parser.add_argument('-l','--directory_to_list', 
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
    meta_obj.component = args['component']
    meta_obj.channel = args['channel']
    meta_obj.remote_dist_dir = args['remote_dist_dir']
    if args['directory_to_list']:
        meta_obj.directory_to_list = args['directory_to_list']
        if not meta_obj.directory_to_list.endswith('/'):
            meta_obj.directory_to_list += '/'
    else:
        meta_obj.directory_to_list = '.'
    if  args['s3_addy'] and "dev-static-rust-lang-org" in args['s3_addy']:
        meta_obj.url_base = "https://dev-static.rust-lang.org"
    else:
        meta_obj.url_base = "https://static.rust-lang.org"
    return meta_obj

def is_tarball_or_installer(f):
    for ext in installer_exts:
        if f.endswith(ext):
            return True
    return False

def build_metadata(meta_obj):
    files = [f for f in os.listdir(meta_obj.directory_to_list) if os.path.isfile(meta_obj.directory_to_list + f)]
    archives = [f for f in files if is_tarball_or_installer(f)]
    for filename in archives:
        d = decompose_name(filename, meta_obj.channel)
        # d will return None if the archive is not in the channel we want
        if d:
            # d contains (triple, component), triple is in target_list
            this_component = d[1]
            triple = d[0]
            shasum = ''
            with open(meta_obj.directory_to_list + filename) as s:
                h = hashlib.sha256()
                h.update(s.read())
                shasum = h.hexdigest()
            (version, comp_list) = get_version_and_components_from_archive(meta_obj.directory_to_list + filename)
            # FIXME move url calculation into the meta object
            url = meta_obj.url_base + '/' + meta_obj.remote_dist_dir + '/' + strftime("%Y-%m-%d") + '/' + filename
            meta_obj.add_pkg(this_component, url, version)
            meta_obj.add_triple(this_component, triple, url, shasum, filename, comp_list)
    return meta_obj

def decompose_name(filename, channel):
    # ASSUMPTIONS: 
    #   * component names do not occur in triples
    #   * the filename ends with .tar.gz
    #   * Things are mostly hyphen-separated
    #   * We only want packages where the channel occurrs in the filename
 
    #   rust-docs   -   nightly   -   i686-apple-darwin    .tar.gz
    #    \    /            |              \    /              |
    #   component       channel           triple          extension
    component = None
    triple = None
    debug("decomposing " + filename)
    if channel not in filename:
        return
    # still here? filename looks like rustc-docs--i686-apple-darwin
    for c in valid_components: 
        if c in filename:
            component = c 
    for t in target_list:
        if t in filename:
            triple = t
    if 'src' in filename:
        triple = 'src'
    if triple and component:
        return (triple, component)


def get_version_and_components_from_archive(a):
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
    ar.close()
    return (version, comp_list)

         
def main():
    m = Meta()
    m = get_arguments(m)
    m = build_metadata(m)
    try:
        m.get_cargo() # Make a better effort to get ahold of some Cargo package info
    except:
        pass
    m.print_metadata()

if __name__ == "__main__":
    main()
