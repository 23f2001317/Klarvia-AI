import { Router, Request, Response } from "express";
import { pool } from "./db";
import { authMiddleware } from "./auth";

const router = Router();

// All routes require authentication
router.use(authMiddleware);

// Get list of all tables
router.get("/tables", async (req: Request, res: Response) => {
  try {
    const { rows } = await pool.query(`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = 'public' 
      ORDER BY table_name
    `);
  res.json({ tables: rows.map((r: any) => r.table_name) });
  } catch (e: any) {
    console.error("Failed to fetch tables:", e);
    res.status(500).json({ error: e?.message || "Failed to fetch tables" });
  }
});

// Get table schema (columns)
router.get("/tables/:tableName/schema", async (req: Request, res: Response) => {
  try {
    const { tableName } = req.params;
    const { rows } = await pool.query(`
      SELECT 
        column_name, 
        data_type, 
        is_nullable,
        column_default
      FROM information_schema.columns 
      WHERE table_schema = 'public' 
        AND table_name = $1
      ORDER BY ordinal_position
    `, [tableName]);
    res.json({ schema: rows });
  } catch (e: any) {
    console.error("Failed to fetch schema:", e);
    res.status(500).json({ error: e?.message || "Failed to fetch schema" });
  }
});

// Get data from a specific table with pagination
router.get("/tables/:tableName/data", async (req: Request, res: Response) => {
  try {
    const { tableName } = req.params;
    const limit = parseInt(req.query.limit as string) || 50;
    const offset = parseInt(req.query.offset as string) || 0;
    
    // Validate table name to prevent SQL injection
    const validTableResult = await pool.query(`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = 'public' AND table_name = $1
    `, [tableName]);
    
    if (validTableResult.rows.length === 0) {
      return res.status(404).json({ error: "Table not found" });
    }

    // Get total count
    const countResult = await pool.query(`SELECT COUNT(*) as total FROM "${tableName}"`);
    const total = parseInt(countResult.rows[0].total);

    // Get data
    const { rows } = await pool.query(`
      SELECT * FROM "${tableName}" 
      ORDER BY created_at DESC 
      LIMIT $1 OFFSET $2
    `, [limit, offset]);
    
    res.json({ 
      data: rows,
      pagination: {
        total,
        limit,
        offset,
        hasMore: offset + limit < total
      }
    });
  } catch (e: any) {
    console.error("Failed to fetch table data:", e);
    res.status(500).json({ error: e?.message || "Failed to fetch table data" });
  }
});

// Update a record
router.put("/tables/:tableName/records/:id", async (req: Request, res: Response) => {
  try {
    const { tableName, id } = req.params;
    const updates = req.body;

    // Validate table exists
    const validTableResult = await pool.query(`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = 'public' AND table_name = $1
    `, [tableName]);
    
    if (validTableResult.rows.length === 0) {
      return res.status(404).json({ error: "Table not found" });
    }

    // Build UPDATE query dynamically
    const keys = Object.keys(updates).filter(k => k !== 'id' && k !== 'created_at');
    if (keys.length === 0) {
      return res.status(400).json({ error: "No fields to update" });
    }

    const setClause = keys.map((key, idx) => `"${key}" = $${idx + 1}`).join(", ");
    const values = keys.map(key => updates[key]);
    values.push(id);

    const query = `UPDATE "${tableName}" SET ${setClause}, updated_at = NOW() WHERE id = $${values.length} RETURNING *`;
    
    const { rows } = await pool.query(query, values);
    
    if (rows.length === 0) {
      return res.status(404).json({ error: "Record not found" });
    }

    res.json({ record: rows[0] });
  } catch (e: any) {
    console.error("Failed to update record:", e);
    res.status(500).json({ error: e?.message || "Failed to update record" });
  }
});

// Delete a record
router.delete("/tables/:tableName/records/:id", async (req: Request, res: Response) => {
  try {
    const { tableName, id } = req.params;

    // Validate table exists
    const validTableResult = await pool.query(`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = 'public' AND table_name = $1
    `, [tableName]);
    
    if (validTableResult.rows.length === 0) {
      return res.status(404).json({ error: "Table not found" });
    }

    const { rowCount } = await pool.query(`DELETE FROM "${tableName}" WHERE id = $1`, [id]);
    
    if (rowCount === 0) {
      return res.status(404).json({ error: "Record not found" });
    }

    res.json({ success: true, message: "Record deleted" });
  } catch (e: any) {
    console.error("Failed to delete record:", e);
    res.status(500).json({ error: e?.message || "Failed to delete record" });
  }
});

export default router;
