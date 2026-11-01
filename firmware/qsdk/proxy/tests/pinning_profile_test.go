package tls

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"math/big"
	"testing"
	"time"
)

// Exercise the actual Xray verifier with an ephemeral certificate carrying
// only a legacy CN, as required by the subscription migration. No user data.
func TestCR8808CertificatePinning(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject: pkix.Name{CommonName: "legacy.invalid"},
		NotBefore: time.Now().Add(-time.Hour),
		NotAfter: time.Now().Add(time.Hour),
		KeyUsage: x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, public, private)
	if err != nil {
		t.Fatal(err)
	}
	pin := sha256.Sum256(der)
	good := (&Config{PinnedPeerCertSha256: [][]byte{pin[:]}}).GetTLSConfig()
	if !good.InsecureSkipVerify || good.VerifyPeerCertificate == nil {
		t.Fatal("pinning must use the custom verifier")
	}
	if err := good.VerifyPeerCertificate([][]byte{der}, nil); err != nil {
		t.Fatalf("correct leaf pin rejected: %v", err)
	}
	wrong := pin
	wrong[0] ^= 1
	bad := (&Config{PinnedPeerCertSha256: [][]byte{wrong[:]}}).GetTLSConfig()
	if err := bad.VerifyPeerCertificate([][]byte{der}, nil); err == nil {
		t.Fatal("incorrect pin accepted")
	}
	ordinary := (&Config{}).GetTLSConfig()
	if ordinary.InsecureSkipVerify {
		t.Fatal("missing pin must retain ordinary certificate validation")
	}
}
