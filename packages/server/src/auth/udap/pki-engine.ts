/**
 * pkijs crypto engine — required for CRL/OCSP signature verification. Uses Node's Web Crypto
 * (Node ≥ 20). Imported for side effect by crl.ts / ocsp.ts. Idempotent.
 */
import { webcrypto } from "node:crypto";
import { CryptoEngine, setEngine } from "pkijs";

type EngineCrypto = ConstructorParameters<typeof CryptoEngine>[0]["crypto"];
setEngine("ronin", new CryptoEngine({ name: "ronin", crypto: webcrypto as unknown as EngineCrypto }));
