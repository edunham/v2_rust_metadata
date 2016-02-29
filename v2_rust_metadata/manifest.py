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

target_list = sorted([ 
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
])

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
        self.datestring = strftime("%Y-%m-%d")
        self.rustversion = "unknown"

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
                if pkg_name == 'rust':
                    self.rustversion = version
            self.pkgs[pkg_name]['url'] = url
            self.pkgs[pkg_name]['src'] = {} 
            self.pkgs[pkg_name]['target'] = d

    def add_triple(self, pkg_name, triple, url, shasum, filename, comp_list = None):
        try:
            if triple == 'src':
                self.pkgs[pkg_name]['src'][triple] = {'url': url,'hash': shasum, 'filename': filename}
            self.pkgs[pkg_name]['target'][triple] = {'url': url,'hash': shasum, 'filename': filename}
            if comp_list:
                self.pkgs[pkg_name]['target'][triple]['components'] = [] 
                for c in comp_list:
                    if c not in valid_components:
                        d = decompose_name(c, '-')
                        if d:
                            (target, comp) = d
                            self.pkgs[pkg_name]['target'][triple]['components'].append(comp)
                        else:
                            e = "Found mystery filename " + c + " in " + filename + " component list"
                            raise Exception(e) 
        except KeyError:
            e = "Tried to add triple " + triple + " to nonexistant package " + pkg_name
            raise Exception(e) 

    def get_cargo(self):
        self.add_pkg('cargo')
        # Cargo is built daily and dumped into baseurl/cargo-dist/
        # TODO find cargo_revs.txt in rust_packaging repo, consult when not
        # nightly
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

    def write_manifest(self):
        toml_name = "channel-" + self.component + '-' + self.channel + ".toml"
        f = open(toml_name, 'w')
        f.write(self.get_preamble())
        if self.component == "rust": 
            f.write(self.get_rust_metadata())
        for c in sorted(self.pkgs):
            if c != 'rust':
                f.write(self.get_pkg_metadata(c))
        f.close()
   
    def get_preamble(self):
        # A manifest will always start with the version and date.
        preamble ='manifest_version = "2"\n' 
        preamble +=  'date = "%s"\n' % self.datestring 
        return preamble

    def get_src_info(self, c):
        info = ""
        try:
            url = self.pkgs[c]['src']['url'] 
            shasum = self.pkgs[c]['src']['hash'] 
            info += "    [pkg.%s.src]\n" % c
            info += '        url = "%s"\n' % url
            info += '        hash = "%s"\n' % shasum
        except KeyError:
            # It's ok not to have a src package
            pass
        return info

    def is_target_available(self, c, t):
        try:
            self.pkgs[c]['target'][t]['url']
            return True
        except KeyError:
            return False

    def get_target_info(self, c, t):
        info = '    [pkg.%s.target.%s]\n' % (c, t)
        try:
            url = self.pkgs[c]['target'][t]['url']                
            sha = self.pkgs[c]['target'][t]['hash']                
            info += '        available = true\n'
            info += '        url = "%s"\n' % url
            info += '        hash = "%s"\n' % sha
        except KeyError:
            info += '        available = false\n'
        return info

    def get_pkg_metadata(self, c):
        info = "[pkg.%s]\n" % c
        try:
            pkg_version = self.pkgs[c]['version']
            if not isinstance(pkg_version, basestring) or len(pkg_version) <= 3:
                pkg_version = self.rustversion
        except KeyError:
            pkg_version = self.rustversion
        info += '    version = "%s"\n' % pkg_version
        info += self.get_src_info(c)
        for t in target_list:
            info += self.get_target_info(c, t)
        return info

    def get_rust_metadata(self):
        c = 'rust'
        info = "[pkg.rust]\n"
        info += '    version = "%s"\n' % self.rustversion
        info += self.get_src_info(c) 
        for t in target_list:
            target = t
            if self.is_target_available(c, t): # T/F = whether it's available
                info += self.get_target_info(c,t)
                for comp in sorted(self.pkgs['rust']['target'][target]['components']):
                    info += "        [[pkg.%s.target.%s.components]]\n" % (c, t)
                    info += '            pkg = "%s"\n' % comp
                    info += '            target = "%s"\n' % target
                # TODO extension logic goes here. Loop over all available
                # platforms for std and docs, etc
        return info

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
            if filename.endswith(".tar.gz"):
                (version, comp_list) = get_version_and_components_from_archive(meta_obj.directory_to_list + filename)
                # FIXME move url calculation into the meta object
                url = meta_obj.url_base + '/' + meta_obj.remote_dist_dir + '/' + meta_obj.datestring + '/' + filename
                meta_obj.add_pkg(this_component, url, version)
                meta_obj.add_triple(this_component, triple, url, shasum, filename, comp_list)
            else:
                # TODO this is where handling installers will go
                pass
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
    m.write_manifest()

if __name__ == "__main__":
    main()
