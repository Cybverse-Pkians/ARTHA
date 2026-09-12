#!/usr/bin/perl
# Minimal static file server for the offline ARTHA harness.
#
# This machine has no Node and no working Python, so there is no `http.server`
# to reach for. Perl ships with macOS and IO::Socket::INET is core.
#
# Handled sequentially and deliberately: a forking version loses the listening
# loop the first time SIGCHLD interrupts accept(), and the harness only ever
# serves one small document — Pyodide itself is fetched from the CDN.
#
#   usage: perl tools/serve.pl [port] [docroot]
use strict;
use warnings;
use IO::Socket::INET;

my $port = shift // 8787;
my $root = shift // ".";

my %TYPES = (
    html => 'text/html; charset=utf-8', js   => 'text/javascript; charset=utf-8',
    css  => 'text/css; charset=utf-8',  json => 'application/json; charset=utf-8',
    svg  => 'image/svg+xml',            wasm => 'application/wasm',
    png  => 'image/png',                ico  => 'image/x-icon',
);

my $server = IO::Socket::INET->new(
    LocalAddr => '127.0.0.1', LocalPort => $port,
    Proto => 'tcp', Listen => 64, ReuseAddr => 1,
) or die "cannot bind :$port — $!\n";

$| = 1;
print "serving $root on http://localhost:$port/\n";

while (1) {
    my $client = $server->accept();
    unless ($client) { select(undef, undef, undef, 0.05); next; }

    my $req = <$client>;
    unless (defined $req) { close $client; next; }

    my ($method, $path) = $req =~ m{^(GET|HEAD)\s+(\S+)\s+HTTP}i;
    while (my $h = <$client>) { last if $h =~ /^\r?\n$/ }

    $path = '/' unless defined $path;
    $path =~ s/\?.*$//;
    $path =~ s{\.\.}{}g;                       # no traversal above the docroot
    $path = '/index.html' if $path eq '/';

    my $file = "$root$path";
    if (-f $file && open(my $fh, '<:raw', $file)) {
        local $/;
        my $body = <$fh>;
        close $fh;
        my ($ext) = $file =~ /\.([A-Za-z0-9]+)$/;
        my $type = $TYPES{lc($ext // '')} // 'application/octet-stream';
        print $client "HTTP/1.1 200 OK\r\n",
                      "Content-Type: $type\r\n",
                      "Content-Length: " . length($body) . "\r\n",
                      "Cache-Control: no-store\r\n",
                      "Connection: close\r\n",
                      "Access-Control-Allow-Origin: *\r\n\r\n";
        print $client $body unless (defined $method && uc($method) eq 'HEAD');
        print "200 $path (" . length($body) . ")\n";
    } else {
        my $body = "404 not found: $path\n";
        print $client "HTTP/1.1 404 Not Found\r\n",
                      "Content-Type: text/plain\r\n",
                      "Content-Length: " . length($body) . "\r\n",
                      "Connection: close\r\n\r\n", $body;
        print "404 $path\n";
    }
    close $client;
}
